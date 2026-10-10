"""Bounded read-only office workbench, outcome-based verifier, OpenEnv server."""
import csv
import io
import json
import re
import secrets
import sqlite3
import time
from uuid import uuid4
from typing import Literal

from openenv.core.env_server.http_server import create_app
from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import Action, Observation, State
from pydantic import Field
from tasks import TASK_IDS, make_task

MAX_STEPS = 24

class OfficeAction(Action):
    operation: Literal['read', 'query', 'write', 'submit'] = Field(description='Read a named source CSV/brief or current artifact; query SQLite source tables; write report.csv or summary.json; submit grades both artifacts and ends.')
    path: str = Field(default='', max_length=80, description='Exact observed filename. write allows only report.csv and summary.json. No filesystem paths.')
    sql: str = Field(default='', max_length=12000, description='One read-only SQLite SELECT or WITH query. Sources are tables named after CSV files without .csv. Up to 200 rows; all results must fit 16000 characters. No external files or writes.')
    content: str = Field(default='', max_length=20000, description='Full artifact text for write: report.csv or summary.json. JSON summary values must be integers. CSV headers and units must match the brief.')

class OfficeObservation(Observation):
    task_id: str = ''
    message: str = ''
    files: list[str] = Field(default_factory=list)
    tables: dict = Field(default_factory=dict)
    steps_left: int = MAX_STEPS


def connect(task):
    db = sqlite3.connect(':memory:', check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 50000)
    db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 12000)
    db.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 100)
    db.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 10)
    for name, rows in task.tables.items():
        columns = list(rows[0])
        defs = ','.join(f'"{k}" {"INTEGER" if isinstance(rows[0][k], int) else "TEXT"}' for k in columns)
        db.execute(f'CREATE TABLE "{name}" ({defs})')
        db.executemany(f'INSERT INTO "{name}" VALUES ({",".join("?" for _ in columns)})', [tuple(x[c] for c in columns) for x in rows])
    db.commit()
    funcs = {'lower', 'upper', 'trim', 'ltrim', 'rtrim', 'length', 'substr', 'substring', 'instr', 'replace',
             'coalesce', 'ifnull', 'nullif', 'abs', 'min', 'max', 'sum', 'total', 'count', 'avg', 'round',
             'row_number', 'rank', 'dense_rank', 'first_value', 'last_value', 'lag', 'lead', 'iif', 'typeof', 'like', 'glob'}
    def authorize(action, a, b, _database, _trigger):
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE): return sqlite3.SQLITE_OK
        # SQLite reports count(*) on a CTE as READ(cte, '', database=None).
        # No physical tables exist outside the source whitelist.
        if action == sqlite3.SQLITE_READ and (a in task.tables or (_database is None and b == '')): return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and (b or '').lower() in funcs: return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    db.set_authorizer(authorize)
    return db


def query(db, sql):
    deadline = time.monotonic() + 1.0
    ticks = 0
    def progress():
        nonlocal ticks
        ticks += 1
        return ticks > 2000 or time.monotonic() > deadline
    db.set_progress_handler(progress, 1000)
    try:
        cursor = db.execute(sql)
        if cursor.description is None: raise ValueError('Only SELECT/CTE results allowed')
        columns = [x[0] for x in cursor.description]
        if len(set(columns)) != len(columns): raise ValueError('Use unique result aliases')
        values = cursor.fetchmany(201)
        if len(values) > 200: raise ValueError('Result exceeds 200 rows; aggregate or filter')
        output = json.dumps({'columns': columns, 'rows': [dict(x) for x in values]}, ensure_ascii=False)
        if len(output) > 16000: raise ValueError('Result exceeds 16000 characters; select fewer columns')
        return output
    finally:
        db.set_progress_handler(None, 0)


def grade(task, artifacts):
    row_score, summary_score = 0.0, 0.0
    diagnostics = []
    try:
        reader = csv.DictReader(io.StringIO(artifacts.get('report.csv', '')))
        if reader.fieldnames != task.columns: raise ValueError('report.csv headers must match brief order exactly')
        submitted = list(reader)
        if len(submitted) > 200 or any(None in r or any(v is None for v in r.values()) for r in submitted):
            raise ValueError('Malformed CSV or more than 200 rows')
        key = task.columns[0]
        keys = [r[key] for r in submitted]
        duplicates = {k for k in keys if keys.count(k) > 1}
        expected = {r[key]: r for r in task.rows}
        correct = 0
        width = len(task.columns)
        for row in submitted:
            target = expected.get(row[key])
            if target is None or row[key] in duplicates: continue
            for col in task.columns:
                if isinstance(target[col], int):
                    valid = bool(re.fullmatch(r'-?\d+', row[col])) and int(row[col]) == target[col]
                else: valid = row[col] == target[col]
                correct += int(valid)
        if not task.rows:
            row_score = 1.0 if not submitted else 0.0
        else: row_score = correct / (max(len(submitted), len(task.rows)) * width)
        diagnostics.append('report parsed; duplicate keys receive no credit')
    except (ValueError, csv.Error, TypeError, OverflowError) as exc:
        diagnostics.append(str(exc)[:180])
    try:
        def unique_pairs(pairs):
            result = {}
            for k, v in pairs:
                if k in result: raise ValueError('Duplicate JSON keys')
                result[k] = v
            return result
        data = json.loads(artifacts.get('summary.json', ''), object_pairs_hook=unique_pairs)
        if not isinstance(data, dict) or set(data) != set(task.summary): raise ValueError('summary.json keys must match brief exactly')
        summary_score = sum(type(data[k]) is int and data[k] == v for k, v in task.summary.items()) / len(task.summary)
        diagnostics.append('summary parsed')
    except (ValueError, TypeError, RecursionError) as exc:
        diagnostics.append(str(exc)[:180])
    reward = 0.6 * row_score + 0.4 * summary_score
    return round(reward, 8), {'report_fraction': round(row_score, 6), 'summary_fraction': summary_score,
                              'diagnostics': diagnostics, 'complete': row_score == summary_score == 1.0}

class OfficeEnvironment(Environment):
    SUPPORTS_CONCURRENT_SESSIONS = True

    def __init__(self):
        self.task = None
        self.db = None
        self.artifacts = {}
        self.ended = False
        self.last_reward = 0.0
        self._state = State(episode_id=str(uuid4()), step_count=0)

    @property
    def state(self): return self._state

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None

    def reset(self, seed=None, task_id=None, **kwargs):
        self.close()
        actual_seed = secrets.randbits(63) if seed is None else seed
        if task_id is None: task_id = TASK_IDS[actual_seed % len(TASK_IDS)]
        self.task = make_task(task_id, actual_seed)
        self.db = connect(self.task)
        self.artifacts = {}
        self.ended = False
        self.last_reward = 0.0
        self._state = State(episode_id=str(uuid4()), step_count=0)
        catalog = {name: {k: 'INTEGER' if isinstance(v, int) else 'TEXT' for k, v in rows[0].items()} for name, rows in self.task.tables.items()}
        return OfficeObservation(task_id=task_id, message=self.task.instructions, files=list(self.task.files), tables=catalog, reward=0.0, done=False)

    def step(self, action, **kwargs):
        if self.task is None: self.reset()
        if self.ended: return OfficeObservation(task_id=self.task.task_id, message='Episode ended; reset required', reward=self.last_reward, done=True, steps_left=0)
        self._state.step_count += 1
        try:
            if action.operation == 'read':
                sources = self.task.files
                if action.path in sources: message = sources[action.path]
                elif action.path in self.artifacts: message = self.artifacts[action.path]
                else: raise ValueError('Unknown filename')
            elif action.operation == 'query': message = query(self.db, action.sql)
            elif action.operation == 'write':
                if action.path not in ('report.csv', 'summary.json'): raise ValueError('Only report.csv and summary.json are writable')
                self.artifacts[action.path] = action.content
                message = f'Stored {action.path} ({len(action.content)} characters). Content not yet graded.'
            else: message = ''
        except (ValueError, sqlite3.Error, OverflowError) as exc:
            message = 'Action error: ' + str(exc)[:250]
        self.ended = action.operation == 'submit' or self._state.step_count >= MAX_STEPS
        if self.ended:
            self.last_reward, result = grade(self.task, self.artifacts)
            message = json.dumps(result)
        return OfficeObservation(task_id=self.task.task_id, message=message, files=list(self.artifacts),
                                 steps_left=max(0, MAX_STEPS - self._state.step_count),
                                 reward=self.last_reward if self.ended else 0.0, done=self.ended)

app = create_app(OfficeEnvironment, OfficeAction, OfficeObservation, env_name='office_workflow_lab', max_concurrent_envs=5)

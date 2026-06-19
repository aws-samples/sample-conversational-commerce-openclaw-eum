"""
CloudFormation Custom Resource handler: DB Initializer
------------------------------------------------------
Called by CloudFormation after the RDS MySQL database is created.

ResourceProperties (from CloudFormation):
  SecretArn      - Secrets Manager secret ARN containing DB credentials
  MasterDbName   - Database name inside MySQL (e.g. "claw_boutique")

On CREATE / UPDATE:
  1. Read DB credentials from the Secrets Manager secret (auto-populated by RDS)
  2. Run schema.sql, schema_additions.sql, seed_demo.sql against the DB

On DELETE:
  No-op — the RDS database and its data are preserved.
"""

import json
import os
import re
import urllib.request
import boto3
import pymysql


# ---------------------------------------------------------------------------
# CloudFormation response helper
# ---------------------------------------------------------------------------

def cfn_send(event, context, status, reason="", data=None, physical_id=None):
    """POST a response to the CloudFormation callback URL."""
    body = json.dumps({
        "Status": status,
        "Reason": reason or f"See CloudWatch log stream: {context.log_stream_name}",
        "PhysicalResourceId": physical_id or event.get("PhysicalResourceId", "db-initializer"),
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": data or {},
    }).encode("utf-8")

    req = urllib.request.Request(
        url=event["ResponseURL"],
        data=body,
        headers={
            "Content-Type": "",          # CloudFormation requires empty Content-Type
            "Content-Length": str(len(body)),
        },
        method="PUT",
    )
    with urllib.request.urlopen(req) as resp:
        print(f"cfn_send: HTTP {resp.status} {resp.reason}")


# ---------------------------------------------------------------------------
# SQL execution helpers
# ---------------------------------------------------------------------------

SQL_DIR = os.path.join(os.path.dirname(__file__), "sql")


def _read_sql(filename):
    path = os.path.join(SQL_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _execute_plain_sql(cursor, sql_text):
    """
    Execute a plain SQL file using pymysql's multi-statement support.
    The connection must be opened with CLIENT.MULTI_STATEMENTS.
    """
    sql_text = sql_text.strip()
    if not sql_text:
        return
    print(f"  Executing SQL ({len(sql_text)} chars)...")
    cursor.execute(sql_text)
    # Consume all result sets from multi-statement execution
    while cursor.nextset():
        pass


def _execute_sql_with_delimiters(cursor, sql_text):
    """
    Execute a SQL file that may contain DELIMITER // ... // blocks
    (used for stored procedures).

    Strategy:
      - Find DELIMITER // blocks and extract the procedure body as a single
        statement.
      - All other content is split on semicolons as normal.
    """
    # Split the file into chunks separated by DELIMITER directives.
    # Pattern: DELIMITER // ... DELIMITER ;
    delimiter_block_re = re.compile(
        r"DELIMITER\s*//\s*(.*?)\s*//\s*DELIMITER\s*;",
        re.DOTALL | re.IGNORECASE,
    )

    parts = []
    last_end = 0
    for m in delimiter_block_re.finditer(sql_text):
        # Text before this DELIMITER block — treat as plain SQL
        before = sql_text[last_end:m.start()]
        parts.append(("plain", before))
        # The body inside the DELIMITER block — single statement (e.g. CREATE PROCEDURE)
        parts.append(("single", m.group(1).strip()))
        last_end = m.end()

    # Remaining text after last DELIMITER block
    parts.append(("plain", sql_text[last_end:]))

    for kind, text in parts:
        if kind == "single":
            stmt = text.strip()
            if stmt:
                print(f"  Executing (block): {stmt[:80]}...")
                cursor.execute(stmt)
        else:
            _execute_plain_sql(cursor, text)


def run_sql_files(conn):
    """Run all three SQL files in order."""
    with conn.cursor() as cursor:
        # 1. Core schema
        print("Running schema.sql ...")
        _execute_plain_sql(cursor, _read_sql("schema.sql"))
        conn.commit()

        # 2. Schema additions (contains DELIMITER // stored procedure blocks)
        print("Running schema_additions.sql ...")
        _execute_sql_with_delimiters(cursor, _read_sql("schema_additions.sql"))
        conn.commit()

        # 3. Demo seed data
        seed_path = os.path.join(SQL_DIR, "seed_demo.sql")
        if os.path.exists(seed_path):
            print("Running seed_demo.sql ...")
            _execute_plain_sql(cursor, _read_sql("seed_demo.sql"))
            conn.commit()
        else:
            print("seed_demo.sql not found — skipping seed step.")


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def handler(event, context):
    print(f"Event: {json.dumps(event)}")

    request_type = event.get("RequestType", "")
    props = event.get("ResourceProperties", {})

    secret_arn    = props["SecretArn"]
    master_dbname = props["MasterDbName"]

    # Use a stable physical resource ID.
    physical_id = "db-initializer"

    # On DELETE: nothing to do — leave the database intact.
    if request_type == "Delete":
        print("DELETE event — no-op.")
        cfn_send(event, context, "SUCCESS", physical_id=physical_id)
        return

    # -----------------------------------------------------------------
    # CREATE / UPDATE
    # -----------------------------------------------------------------
    try:
        sm_client = boto3.client("secretsmanager")

        # 1. Read DB credentials from Secrets Manager (populated by RDS)
        print(f"Reading DB credentials from secret: {secret_arn}")
        secret_resp = sm_client.get_secret_value(SecretId=secret_arn)
        creds = json.loads(secret_resp["SecretString"])

        db_host = creds["host"]
        db_port = int(creds.get("port", 3306))
        db_user = creds["username"]
        db_password = creds["password"]
        print(f"DB endpoint: {db_host}:{db_port}")

        # 2. Connect to MySQL and run SQL files
        print(f"Connecting to MySQL at {db_host}:{db_port} ...")
        conn = pymysql.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            database=master_dbname,
            charset="utf8mb4",
            autocommit=False,
            connect_timeout=30,
            client_flag=pymysql.constants.CLIENT.MULTI_STATEMENTS,
        )
        try:
            run_sql_files(conn)
        finally:
            conn.close()

        print("DB initialization complete.")
        cfn_send(
            event, context, "SUCCESS",
            data={"DbHost": db_host, "DbPort": str(db_port)},
            physical_id=physical_id,
        )

    except Exception as exc:
        print(f"ERROR: {exc}")
        cfn_send(
            event, context, "FAILED",
            reason=str(exc),
            physical_id=physical_id,
        )
        raise

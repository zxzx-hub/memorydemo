import asyncio, asyncpg, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def main():
    conn = await asyncpg.connect(
        host='127.0.0.1', port=5432,
        user='memory', password='memory',
        database='memory'
    )
    rows = await conn.fetch('SELECT DISTINCT tenant_id FROM memory_events ORDER BY tenant_id')
    print('=== Database tenants ===')
    for r in rows:
        print(f'  tenant_id={r[0]}')

    rows2 = await conn.fetch('SELECT tenant_id, COUNT(*) as cnt FROM memory_events GROUP BY tenant_id ORDER BY cnt DESC')
    print()
    print('=== Events per tenant ===')
    for r in rows2:
        print(f'  tenant_id={r[0]}  events={r[1]}')

    rows3 = await conn.fetch('''
        SELECT tenant_id, workspace_id, task_id, session_id,
               LEFT(content, 60) as preview,
               created_at
        FROM memory_events ORDER BY created_at DESC LIMIT 10
    ''')
    print()
    print('=== Last 10 events ===')
    for r in rows3:
        print(f'  tenant={r[0]}  ws={r[1]}  task={r[2]}  sess={r[3]}  content="{r[4]}"  {r[5]}')

    await conn.close()

asyncio.run(main())

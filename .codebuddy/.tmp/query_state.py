import asyncio, asyncpg, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def main():
    conn = await asyncpg.connect(
        host='127.0.0.1', port=5432,
        user='memory', password='memory',
        database='memory'
    )
    print('=== All tables in memory schema ===')
    rows = await conn.fetch("""
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename
    """)
    for r in rows:
        print(f'  {r[0]}')

    print()
    print('=== Counts for memory-related tables ===')
    for table in [r[0] for r in rows]:
        if any(k in table for k in ['memory', 'event', 'consolidat', 'tenant', 'governance', 'outbox', 'evidence', 'checkpoint', 'candidate', 'audit', 'exact', 'vector', 'graph', 'working']):
            try:
                n = await conn.fetchval(f'SELECT COUNT(*) FROM "{table}"')
                print(f'  {table:38s} {n:>4} rows')
            except Exception as e:
                print(f'  {table:38s} ERROR: {e}')

    print()
    print('=== Cursor ===')
    try:
        rows = await conn.fetch('SELECT * FROM consolidation_cursors')
        for r in rows:
            print(f'  {dict(r)}')
    except Exception as e:
        print(f'  err: {e}')

    print()
    print('=== LTM (long_term_memory) sample ===')
    try:
        rows = await conn.fetch('SELECT memory_id, memory_type, status, LEFT(content, 60) FROM long_term_memory ORDER BY memory_id LIMIT 5')
        for r in rows:
            print(f'  {r[0]}  {r[1]}  {r[2]}  "{r[3]}"')
    except Exception as e:
        print(f'  err: {e}')

    await conn.close()

asyncio.run(main())

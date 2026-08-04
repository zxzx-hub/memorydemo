import asyncio, asyncpg, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def main():
    conn = await asyncpg.connect(
        host='127.0.0.1', port=5432,
        user='memory', password='memory',
        database='memory'
    )
    # 先看 working_memory 有哪些列
    cols = await conn.fetch("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'working_memory'
        ORDER BY ordinal_position
    """)
    print('=== working_memory columns ===')
    for c in cols:
        print(f'  {c[0]}  ({c[1]})')

    n = await conn.fetchval('SELECT COUNT(*) FROM working_memory')
    print(f'\ntotal rows: {n}')

    if n > 0:
        rows = await conn.fetch('SELECT * FROM working_memory ORDER BY updated_at DESC')
        for r in rows:
            print(f'\n--- row ---')
            for k, v in dict(r).items():
                s = str(v)
                if len(s) > 100:
                    s = s[:100] + '...'
                print(f'  {k}: {s}')

    await conn.close()

asyncio.run(main())

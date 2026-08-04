import asyncio, asyncpg, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def main():
    conn = await asyncpg.connect(
        host='127.0.0.1', port=5432,
        user='memory', password='memory',
        database='memory'
    )

    # Check the deterministic trigger phrase
    PHRASE = "以后给我讲技术方案时，先讲总体架构，再展开字段和代码"
    print('=== Checking if any events contain the candidate trigger phrase ===')
    rows = await conn.fetch("""
        SELECT event_id, LEFT(content, 80), created_at
        FROM memory_events
        WHERE content LIKE '%' || $1 || '%'
        ORDER BY created_at
    """, PHRASE)
    if rows:
        for r in rows:
            print(f'  {r[0]}  "{r[1]}"  {r[2]}')
    else:
        print('  NO EVENT contains the phrase!')
        print(f'  Phrase: "{PHRASE}"')

    # What do events actually say?
    print()
    print('=== All events content sample ===')
    rows = await conn.fetch("""
        SELECT event_id, LEFT(content, 80)
        FROM memory_events
        WHERE tenant_id = 'tenant_a'
        ORDER BY created_at
    """)
    for r in rows:
        print(f'  {r[0]}  "{r[1]}"')

    await conn.close()

asyncio.run(main())

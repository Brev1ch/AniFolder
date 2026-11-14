-- Comparison on the identical 500-row seed. No planner settings changed for main variants.
\echo '5a: date_part, no kind (original)'
EXPLAIN (ANALYZE, BUFFERS) SELECT id, title_en FROM anime WHERE date_part('year', aired_on) >= 2010 AND date_part('year', aired_on) <= 2020 ORDER BY aired_on DESC NULLS LAST, id LIMIT 20;
\echo '5b: date range, no kind'
EXPLAIN (ANALYZE, BUFFERS) SELECT id, title_en FROM anime WHERE aired_on >= DATE '2010-01-01' AND aired_on < DATE '2021-01-01' ORDER BY aired_on DESC NULLS LAST, id LIMIT 20;
\echo '5c: date_part with kind'
EXPLAIN (ANALYZE, BUFFERS) SELECT id, title_en FROM anime WHERE kind = 'tv' AND date_part('year', aired_on) >= 2010 AND date_part('year', aired_on) <= 2020 ORDER BY aired_on DESC NULLS LAST, id LIMIT 20;
\echo '5d: date range with kind'
EXPLAIN (ANALYZE, BUFFERS) SELECT id, title_en FROM anime WHERE kind = 'tv' AND aired_on >= DATE '2010-01-01' AND aired_on < DATE '2021-01-01' ORDER BY aired_on DESC NULLS LAST, id LIMIT 20;
\echo 'Equivalence (all matches, both directions, expected 0)'
WITH old AS (SELECT id FROM anime WHERE date_part('year', aired_on) BETWEEN 2010 AND 2020), new AS (SELECT id FROM anime WHERE aired_on >= DATE '2010-01-01' AND aired_on < DATE '2021-01-01') SELECT count(*) AS differences FROM ((SELECT * FROM old EXCEPT SELECT * FROM new) UNION ALL (SELECT * FROM new EXCEPT SELECT * FROM old)) d;
\echo 'DIAGNOSTIC ONLY: enable_seqscan=off; proves index applicability, not planner preference'
BEGIN;
SET LOCAL enable_seqscan=off;
\echo 'Search: both GIN indexes required by OR'
EXPLAIN (ANALYZE, BUFFERS) SELECT id FROM anime WHERE title_ru ILIKE '%Test Anime 7%' OR title_en ILIKE '%Test Anime 7%';
\echo 'date_part with kind: inspect Index Cond vs Filter'
EXPLAIN (ANALYZE, BUFFERS) SELECT id, title_en FROM anime WHERE kind = 'tv' AND date_part('year', aired_on) >= 2010 AND date_part('year', aired_on) <= 2020 ORDER BY aired_on DESC NULLS LAST, id LIMIT 20;
\echo 'date range with kind: inspect Index Cond vs Filter'
EXPLAIN (ANALYZE, BUFFERS) SELECT id, title_en FROM anime WHERE kind = 'tv' AND aired_on >= DATE '2010-01-01' AND aired_on < DATE '2021-01-01' ORDER BY aired_on DESC NULLS LAST, id LIMIT 20;
ROLLBACK;

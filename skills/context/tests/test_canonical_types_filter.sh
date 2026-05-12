#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init >/dev/null
"$SHCTX" migrate >/dev/null

db=".shepherd/root.db"
project_id=$(jq -r '.id' .shepherd/project.json)
now=$(date +%s)

# Insert a mix of symbols: structs, enums, traits, fns, consts, modules.
# Only the first three should appear in v_canonical_types post-0003.
sqlite3 "$db" <<SQL
INSERT INTO index_symbols (id,project_id,name,kind,package,file_path,line,visibility,signature,doc_summary,language,hash,refreshed_at)
VALUES
  ('1','$project_id','BookSnapshot','struct','probe','probe/src/lib.rs',1,'pub','pub struct BookSnapshot','','rust','h1',$now),
  ('2','$project_id','Tick','trait','probe','probe/src/lib.rs',2,'pub','pub trait Tick','','rust','h2',$now),
  ('3','$project_id','Side','enum','probe','probe/src/lib.rs',3,'pub','pub enum Side','','rust','h3',$now),
  ('4','$project_id','allocate','fn','probe','probe/src/lib.rs',4,'pub','pub fn allocate','','rust','h4',$now),
  ('5','$project_id','VERSION','const','probe','probe/src/lib.rs',5,'pub','pub const VERSION','','rust','h5',$now),
  ('6','$project_id','helpers','mod','probe','probe/src/lib.rs',6,'pub','pub mod helpers','','rust','h6',$now);
SQL

# v_canonical_types should return ONLY struct/enum/trait kinds (3 rows).
n=$(sqlite3 "$db" "SELECT COUNT(*) FROM v_canonical_types WHERE project_id='$project_id';")
[[ "$n" == "3" ]] || { echo "FAIL: v_canonical_types expected 3 rows (struct/enum/trait only), got $n" >&2; exit 1; }

# v_canonical_symbols should return ALL 6 (the broader query).
m=$(sqlite3 "$db" "SELECT COUNT(*) FROM v_canonical_symbols WHERE project_id='$project_id';")
[[ "$m" == "6" ]] || { echo "FAIL: v_canonical_symbols expected 6 rows (all pub), got $m" >&2; exit 1; }

echo "PASS: test_canonical_types_filter.sh"

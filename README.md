# archive-verify

Find disk space that can be reclaimed safely, and archive old folders with proof
that every file made it into the archive.

Standard library only.

## Why it matters for IT operations

"The disk is full" is a daily ticket. The risky part is not finding big folders,
it is removing data without being sure a good copy exists. This tool splits the
job into safe steps:

1. **`plan`** lists rebuildable folders (`.venv`, `node_modules`, caches, build
   output) that come back from a requirements file, and the largest folders
   overall. It only reads.
2. **`pack`** zips one folder into a vault, then reads every file back out of the
   zip and compares its SHA-256 with the original. If even one file differs, the
   zip is discarded. Rebuildable subfolders are skipped and listed. A
   `.proof.json` file records every hash.
3. **`verify`** re-checks a pack against its proof at any later time.
4. **`unpack`** restores into an empty folder only, so it can never overwrite
   live data.

Nothing in the tool deletes anything. `pack` prints the command to remove the
original, so a person makes that decision after reading the proof.

## Run

```text
python archive_verify.py plan old-projects
python archive_verify.py pack old-projects/inventory-app --vault vault
python archive_verify.py verify vault/inventory-app.zip
python archive_verify.py unpack vault/inventory-app.zip restored
```

## Sample output

A real run on a small demo tree (random file contents, so the zip does not
compress them):

```text
> python archive_verify.py plan old-projects
Rebuildable folders under old-projects: 4.7 MB in 3 folders
         3.5 MB        1 files  inventory-app/.venv
         1.2 MB        1 files  inventory-app/node_modules
         0.0 MB        1 files  ticket-portal/__pycache__
Largest folders under old-projects:
         4.7 MB        4 files  inventory-app
         0.0 MB        2 files  ticket-portal

> python archive_verify.py pack old-projects/inventory-app --vault vault
{
 "ok": true,
 "pack": "inventory-app.zip",
 "files": 2,
 "rebuildable_not_packed": 2,
 "original_bytes": 16000,
 "pack_bytes": 16236,
 "remove_original_with": "Remove-Item -LiteralPath \"old-projects\\inventory-app\" -Recurse"
}

> python archive_verify.py verify vault/inventory-app.zip
{
 "ok": true,
 "files": 2,
 "mismatched": []
}

> python archive_verify.py unpack vault/inventory-app.zip restored
{
 "ok": true,
 "files": 2
}

> python archive_verify.py unpack vault/inventory-app.zip restored
{
 "ok": false,
 "why": "restored is not empty; nothing was written"
}
```

## Tests

```text
> python -m unittest -v test_archive_verify
Ran 5 tests in 0.066s
OK
```

The tests cover the planner, the pack proof, refusal to overwrite a pack,
detection of a hash mismatch, and a full pack and restore round trip.

## License

MIT

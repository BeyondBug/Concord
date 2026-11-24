# Benchmark

A labeled corpus for measuring security scanners, and Concord's arbitration,
by precision and recall instead of by claims.

## Layout

| Path | What |
|---|---|
| `repos.yaml` | The corpus: each repository pinned to an exact commit, with its license and kind (`vulnerable` or `clean`). |
| `labels/<repo>.json` | Ground truth for one repository, validated by `expected.schema.json`. |
| `rulemap.yaml` | Maps each tool's rule IDs to a shared issue class, so different tools are scored against the same labels. |
| `fixtures/` | Clean code written for the benchmark. Any alert on it is a false positive. |
| `fetch.py` | Clones every repository at its pinned commit into `.bench/`. |
| `score.py` | Scores any tool's SARIF output against the labels. |

## How a label is made

A label is a real problem at a place in the code: file, line range, issue
class, severity and a short reason written by the reviewer. Labels do not come
from any single scanner. Candidates are collected from several tools and from
each project's own list of intentional vulnerabilities, then a human checks
every one against the code:

- real problem: added to `findings`;
- not a real problem: added to `rejected` with the reason, so a tool that
  reports it is charged a false positive.

`scope` lists the paths that were reviewed completely. Results outside it are
ignored rather than guessed at.

## Scoring

```bash
python -m benchmark.fetch
checkov -d .bench/terragoat -o sarif --output-file-path /tmp/checkov
python -m benchmark.score --repo terragoat /tmp/checkov/results_sarif.sarif --root "$PWD/.bench/terragoat"
```

A result is a true positive when its file matches a label, its line is inside
the label's range (two lines of slack either side), and its rule maps to the
label's class. Every result lands in exactly one bucket: `tp`, `duplicate`,
`fp`, `unreviewed` (in scope but not judged yet), `unmapped` (rule missing
from `rulemap.yaml`) or `out_of_scope`. Precision is `tp / (tp + fp)` and
recall is `tp / (tp + missed labels)`. Unreviewed and unmapped results are
reported, never silently counted as right or wrong; `--fail-on-unreviewed`
turns them into a CI failure.

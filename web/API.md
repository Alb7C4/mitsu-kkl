# Web API (PC server `mut_web.py` and the future Pico W firmware)

The page in this folder (`index.html`, `app.js`, `style.css`) talks to its server only through
the endpoints below, so any server that implements them can host it. All bodies are JSON (UTF-8).
PIDs are two-digit uppercase hex strings (`"07"`, `"3A"`).

## Static files

`GET /` → `index.html`, `GET /app.js`, `GET /style.css`.

## Requests

| method and path | body | answer |
|---|---|---|
| `GET /api/info` | – | `{"version": "0.1.2", "server": "pc" \| "pico", "ifaces": [{"key", "label"}], "iface": key}` |
| `GET /api/state` | – | snapshot, same shape as the `state` event below |
| `GET /api/defs` | – | `{"pids": {"07": {"name", "conv", "unit", "active"}}, "dtc": [{"bit", "code", "desc"}]}` |
| `PUT /api/defs` | `{"pid": "07", "name", "conv", "unit"}` | `{"ok": true}` or HTTP 400 `{"error": "..."}` (invalid conversion) |
| `POST /api/pids` | `{"text": "07,14,20-2F"}` or `{"pids": ["07", "14"]}`, optional `"temporary": true` | `{"pids": [...], "rejected": [...]}` |
| `POST /api/connect` | `{"iface": key}` (optional) | `{"ok": true}` |
| `POST /api/disconnect` | – | `{"ok": true}` |

`POST /api/pids` replaces the polled list for every client. Without `temporary` the list is also
stored as the "on list" flags of the definitions file; the fault-code view uses `temporary`.
Only read requests are accepted: `00–BF` and `FD–FF`; anything else ends up in `rejected`.

## Events: `GET /api/events` (Server-Sent Events)

One JSON object per `data:` line. A new client first gets `state`.

| `type` | fields | when |
|---|---|---|
| `state` | `status` (as in the `status` event), `pids`, `values` (`{"07": 135 \| null}`), `rate` | on subscribe |
| `status` | `code`, `detail`, `ecu_id`, `iface` | connection state changes |
| `values` | `v` (`{"07": 135, "21": null}`), optional `t` (ms since epoch; the Pico has no clock, so the page uses its own time) | every ~100 ms, only PIDs read since the last batch; `null` = no answer |
| `rate` | `reads` (per s), `cycle` (s per pass) | once a second while connected |
| `pids` | `pids` | the polled list changed |
| `defs` | – | definitions changed; clients reload `GET /api/defs` |

Status codes: `idle`, `opening`, `connecting` (`detail` = init method being tried, may be empty),
`no_response` (`detail` = init method and probe outcome), `connected` (`ecu_id`, `iface`,
`detail` = init method that worked, may be empty), `lost`, `error` (`detail` = message).

Conversions (`conv`) are evaluated in the browser: an expression in `x` (raw byte 0–255) with
numbers, `+ - * / // % & | ^ >>`, parentheses, `abs min max round`, or the keywords `dtc`,
`dtc2` (fault code bits of the first / second byte) and `bin`.

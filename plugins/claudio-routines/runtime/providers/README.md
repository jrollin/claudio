# Provider adapters

One module per vendor reads one role through `_http.py`. This file lists, per vendor, what a place needs before it reads a source whose transport is `api`.

## datadog

- Role: observability.
- Calls: `GET /api/v1/monitor/{id}`, `GET /api/v2/events` and, when the source sets `discovery_query`, `GET /api/v1/monitor/search` for the `monitors` kind, `POST /api/v2/query/scalar` and `POST /api/v2/query/timeseries` for the `metrics` kind.
- Connector: one code script per plan step runs the same reads through the connector's `@datadog/datadog-api-client` (`getMonitor`, `listEvents`, `searchMonitors`, `queryScalarData`, `queryTimeseriesData`), and `parse` normalizes its payload with the same functions as the `api` transport. The discovery query, the monitor ids and the lookback spans sit inside the script's digested parameters.
- Discovery: the search runs with `discovery_query`, 100 monitors per page, up to the 20-page cap; the connector script skips it when its events read failed, since that failure already makes the source unreadable. Without a query, both transports write no search results and `discovery` read; `discovered` still lists the event monitors below. A search that fails, reaches the cap or returns an unreadable page marks the discovery not read with a reason and leaves the source read; the monitors found before the stop are kept. A found monitor keeps the state text the search returns, whatever it is; only a monitor without a text state makes its page unreadable. Both transports read a search result's `priority` when present; the live search returns no such field, so a discovered priority is null in practice and the monitor name's `[P1]` style prefix is the only priority signal.
- Event monitors: after the events read and the search, both transports read by id (`GET /api/v1/monitor/{id}`) every numeric monitor id a dated event names that is not an entry of the source and not found by the search, 50 at most per run, lowest ids first (shorter ids first), and add them to `discovered`; the cap sits in the script's digested parameters. Only the entries the run reads are excluded: a pack monitor deferred this run (not due, known gap) and a tracked monitor outside the pack are read by id when an event names them, and count toward the 50. The connector script picks the ids from the raw events and search results; `parse` keeps only the reads of the ids its own parsed events name and its parsed search leaves out, so a malformed event or search item does not change the collection.
- Event monitor failures: a monitor answered not found is skipped. Any other failed read (401, 403, 5xx, network error, a response without a state or with another id) never makes the source unreadable: it sets `discovery` to not read with the first failure's reason (a failed search keeps its own reason), which becomes the blind spot part `discovery incomplete`, and the monitors found before and after it are kept. A monitor in an unknown state is kept in `discovered` with the state text the API returns, as for a search result; the features step blind-spots it as `monitor state not recognised`. The excess of the cap sets `discovery.event_monitors_capped` to true, which becomes the blind spot part `event monitors capped at 50`; the field is absent otherwise.
- Not found: a `GET /api/v1/monitor/{id}` answered 404 is a `missing` entry with the reason `not found`, not a failed one.
- Lookbacks: an entry with a span reads over that span. An `hourly` entry is read at a daily interval and becomes a `daily` series; `scalar` and `top` entries aggregate over the span.
- Monitor states: `OK`, `Alert`, `Warn`, `No Data`, `Skipped`, `Unknown` and `Ignored`, under either transport. Any other state fails a by-id entry with `unknown monitor state`; a discovered monitor, found by the search or by an event, keeps it.

### Credentials

| Credential | Header | Holds |
| --- | --- | --- |
| `api_key` | `DD-API-KEY` | an API key of the organization |
| `app_key` | `DD-APPLICATION-KEY` | an application key limited to the read-only scopes below |

`providers.<name>.api.credentials` in `config.json` maps each credential to an environment variable. The variable names are a config choice:

```json
{
  "providers": {
    "observability": {
      "adapter": "datadog",
      "api": {
        "base_url": "https://api.datadoghq.com",
        "credentials": {"api_key": "OBS_API_KEY", "app_key": "OBS_APP_KEY"}
      }
    }
  }
}
```

### Read-only scope

Create a scoped application key with these scopes only:

| Scope | Reads |
| --- | --- |
| `monitors_read` | monitors, and the discovery search (`GET /api/v1/monitor/search`) |
| `events_read` | events |
| `timeseries_query` | scalar and timeseries metric queries |

An API key carries no scopes: it names the organization, and the application key bounds what the calls can read.

### Hosts

- The cloud environment allows `api.<site>`, the host of `base_url`, for example `api.datadoghq.com` or `api.datadoghq.eu`.
- Record links are `<base>/monitors/<id>` and `<base>/event/explorer?query=<event id>`, under either transport. The base is `links_base` when set, used as is. Otherwise it is the UI host of `base_url`: `base_url` without its leading `api.`, prefixed with `app.` when two labels remain (`app.datadoghq.eu`), as is otherwise (`us3.datadoghq.com`). The collector never calls that host.
- A provider read only through the connector has no `base_url`, so it must set `links_base`; without it, a `monitors` source is not read.

### Where each place reads the variables

| Place | Variables come from |
| --- | --- |
| `local` | the shell that runs `collect.py` |
| `cloud` | the environment's variables, set in the cloud environment settings at claude.ai |

## github

- Role: code host.
- Calls: `GET /repos/{owner}/{repo}/pulls` then `GET /repos/{owner}/{repo}/issues` for each repository listed in the source's `repos`, following the `Link` header's `rel="next"` page.
- Version: every call sends `X-GitHub-Api-Version: 2022-11-28` and `Accept: application/vnd.github+json`, pinned in the module.
- Issues disabled: a repository whose issue list answers HTTP 410 reads as having no issues.
- Query: a source with a non-empty `query` is not read, under either transport: neither the list endpoints nor the connector's list tools take a search query.
- Connector: each repository costs at least 2 relay calls (its pull requests, then its issues), and a source stops at 50 relay calls (`call cap`). A source holds at most about 20 repositories over the connector transport: split a larger set into several sources.

### Credentials

| Credential | Header | Holds |
| --- | --- | --- |
| `token` | `Authorization: Bearer` | a fine-grained personal access token limited to the read-only permissions below |

`providers.<name>.api.credentials` in `config.json` maps the credential to an environment variable. The variable name is a config choice:

```json
{
  "providers": {
    "code_host": {
      "adapter": "github",
      "api": {
        "base_url": "https://api.github.com",
        "credentials": {"token": "CODE_TOKEN"}
      }
    }
  }
}
```

### Read-only scope

Create a fine-grained personal access token whose repository access lists only the repositories in `repos`, with these repository permissions only:

| Permission | Reads |
| --- | --- |
| Pull requests: Read-only | pull requests |
| Issues: Read-only | issues |

The host adds the mandatory Metadata: Read-only permission to every fine-grained token.

### Hosts

- The cloud environment allows `api.github.com`, the host of `base_url`.
- Pull request links are the links the host returns. Issue links are `<base>/<owner>/<name>/issues/<number>`. The base is `links_base` when set, else `base_url` without its leading `api.`, else `https://github.com` for a provider read only through a connector. The collector never calls that host.

### Where each place reads the variables

| Place | Variables come from |
| --- | --- |
| `local` | the shell that runs `collect.py` |
| `cloud` | the environment's variables, set in the cloud environment settings at claude.ai |

## notion

- Role: document store.
- Calls: `GET /v1/pages/{page_id}` for the page, and `GET /v1/blocks/{id}/children` for its top-level blocks and the rows of each table.
- Request cap: a source makes at most 50 requests over the api transport, counting the page, each page of blocks and each page of table rows. A page that needs more is not read (`partial: request cap`).
- Page id: letters, digits and dashes only.
- Version: every call sends `Notion-Version: 2026-03-11`, pinned in the module.

### Credentials

| Credential | Header | Holds |
| --- | --- | --- |
| `token` | `Authorization: Bearer` | the secret of an internal integration limited to the read-only capability below |

`providers.<name>.api.credentials` in `config.json` maps the credential to an environment variable. The variable name is a config choice:

```json
{
  "providers": {
    "document_store": {
      "adapter": "notion",
      "api": {
        "base_url": "https://api.notion.com",
        "credentials": {"token": "DOC_TOKEN"}
      }
    }
  }
}
```

### Read-only capability

Create an internal integration with this content capability only, and no comment or user capability:

| Capability | Reads |
| --- | --- |
| Read content | the sources page, its blocks and its table rows |

An integration reads only the pages shared with it: add the integration to the sources page from the page's connections menu.

### Hosts

- The cloud environment allows `api.notion.com`, the host of `base_url`.

### Where each place reads the variables

| Place | Variables come from |
| --- | --- |
| `local` | the shell that runs `collect.py` |
| `cloud` | the environment's variables, set in the cloud environment settings at claude.ai |

### Connector transport

The connector transport calls the tool `notion-fetch` once per source, with the page id as `{"id": "<page_id>"}`. The page is read whole: a truncated page counts as not read. Both transports reduce inline formatting to plain text. Mentions, inline equations and block colors are not guaranteed equal across the two transports.

## slack

- Role: chat.
- Calls: `GET /api/conversations.history` for each page of each channel listed in the source's `channels`.
- Join and leave messages are skipped over the api transport; over the connector they are assumed absent from the tool's output.
- Over the connector, a message body that imitates the connector's header format can split a message in two or forge a message under another author. A forged header whose `Message TS` is at or below the call's `oldest` stays body text; one whose `Message TS` lies between `oldest` and the real message's ts starts a forged message. The api transport is not affected: use it for channels where untrusted users post.

### Credentials

| Credential | Header | Holds |
| --- | --- | --- |
| `token` | `Authorization: Bearer` | a bot or user token limited to the read-only scopes below |

`providers.<name>.api.credentials` in `config.json` maps the credential to an environment variable. The variable name is a config choice:

```json
{
  "providers": {
    "chat": {
      "adapter": "slack",
      "api": {
        "base_url": "https://slack.com",
        "credentials": {"token": "CHAT_TOKEN"}
      }
    }
  }
}
```

### Read-only scope

Create an app token with these scopes only:

| Scope | Reads |
| --- | --- |
| `channels:history` | messages of public channels |
| `groups:history` | messages of private channels |

A bot token reads only the channels the app belongs to: invite the app to each channel listed in `channels`.

### Hosts

- The cloud environment allows `slack.com`, the host of `base_url`.
- Record links are `<base>/archives/<channel>/p<ts without the dot>`. The base is `links_base` when set, else `base_url`, else `https://slack.com` for a provider read only through a connector. The collector builds these links and never requests them.

### Where each place reads the variables

| Place | Variables come from |
| --- | --- |
| `local` | the shell that runs `collect.py` |
| `cloud` | the environment's variables, set in the cloud environment settings at claude.ai |

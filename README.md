# AIResearch

AIResearch is a Python-first paper discovery and recommendation pipeline for arXiv and Hugging Face Daily Papers. It helps operators collect candidate papers, score them against a configurable research focus, and publish summaries to downstream channels such as email and Obsidian.

AIResearch 是一个以 Python 为主入口的论文发现与推荐流水线，面向 arXiv 与 Hugging Face Daily Papers。它用于按研究主题收集候选论文、执行多阶段筛选和评分，并将结果输出到邮件、Obsidian 等下游渠道。

## Positioning / 项目定位

- Research-ops pipeline, not a web app.
- Cross-platform CLI: source checkout or installed package both work.
- Extensible through local MCP adapters and YAML/JSON configuration.
- Designed for reproducible local operation, not zero-config hosted deployment.

- 这是研究运营型流水线，不是 Web 应用。
- 官方入口是跨平台 CLI，既支持源码运行，也支持安装后运行。
- 通过本地 MCP 适配器和 YAML/JSON 配置进行扩展。
- 面向可复现的本地运行，而不是零配置云托管发布。

## Capability Boundaries / 能力边界

What the project does:

- Discover papers from arXiv keyword queries, HF daily papers, and HF trending sources.
- Apply stage-1 keyword/topic heuristics and downstream candidate scoring.
- Pull LaTeX sources when available, clean text, and generate analysis artifacts.
- Optionally send notifications and write notes into an Obsidian vault.

What the project does not do by itself:

- It does not provide a browser UI.
- It does not bundle third-party credentials or hosted MCP services.
- It does not currently persist a public seen-paper dedupe cache.

## Install / 安装

Development install:

```bash
python -m pip install -r requirements-dev.txt
python -m pip install -e .
```

If you only want the runtime dependencies, `requirements.txt` is the smaller install surface, but editable install is recommended for local iteration and GitHub contributors.

如果你只需要运行依赖，可以只安装 `requirements.txt`，但对于本地调试和 GitHub 协作，推荐继续执行可编辑安装 `python -m pip install -e .`。

## Configuration / 配置准备

1. Create `config.local.yaml` from [config.example.yaml](/G:/AIResearch/config.example.yaml).
2. Create `mcp.local.json` from [mcp.example.json](/G:/AIResearch/mcp.example.json).
3. Fill in local-only values such as recipients, vault path, and credentials.
4. Export any required environment variables before running.

Recommended environment variables:

- `SEMANTIC_SCHOLAR_API_KEY`
- `GITHUB_TOKEN`
- `EMAIL_ACCOUNT_NAME` when using MCP email delivery
- Optional: `AIRESEARCH_CONFIG`, `AIRESEARCH_MCP_CONFIG`, `OBSIDIAN_VAULT`

配置模板是公开文件；`config.local.yaml` 与 `mcp.local.json` 是本地文件，不应提交到 GitHub。

## Run / 运行

Module entrypoint from a source checkout:

```bash
python -m airesearch --config config.local.yaml --run-once
```

Installed console script:

```bash
airesearch --config config.local.yaml --run-once
```

Date-range example:

```bash
python -m airesearch --config config.local.yaml --run-once --force-run --start-date 2026-03-01 --end-date 2026-03-07
```

Optional log file:

```bash
python -m airesearch --config config.local.yaml --run-once --log-file output/logs/latest.log
```

`ops/` still contains optional PowerShell helpers for local operators, but they are no longer the primary public interface.

## MCP Adapters / MCP 适配器

Public example module entrypoints:

```bash
python -m airesearch.mcp.arxiv
python -m airesearch.mcp.hf_papers
python -m airesearch.mcp.scholarly
python -m airesearch.mcp.github
python -m airesearch.mcp.obsidian
```

The bundled [mcp.example.json](/G:/AIResearch/mcp.example.json) is aligned with those module paths. The email backend still assumes an external `mcp-email-server` compatible service.

## Output Layout / 输出目录说明

- `output/out/<run_id>/run_summary.json`: per-run summary payload.
- `output/latest_run.txt`: pointer to the latest run directory.
- `state/last_run.json`: daily run guard state.
- `prompts/`: prompt assets used by the pipeline.
- `configs/`: whitelist and related public config assets.

More detailed setup and usage notes live in [docs/usage.md](/G:/AIResearch/docs/usage.md) and [docs/seen_papers.md](/G:/AIResearch/docs/seen_papers.md).

## Test / 测试

```bash
python -m pytest -q
```

GitHub Actions verifies the package on Python 3.11 and 3.12 across Ubuntu, Windows, and macOS. CI also checks both `python -m airesearch --help` and `airesearch --help`.

## Security / 安全

- Never commit `config.local.yaml`, `mcp.local.json`, or `.env`.
- Keep API keys, SMTP credentials, and email account settings in environment variables.
- Review generated logs and output artifacts before sharing them publicly.
- Treat `output/` and `state/` as local runtime data, not source-controlled assets.

## Agent Notes / 代理说明

[AGENTS.md](/G:/AIResearch/AGENTS.md) records repository conventions and the current release-hardening tracker for coding agents. It is documentation only and does not affect runtime behavior.


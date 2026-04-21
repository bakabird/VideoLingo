---
name: let-gemini-review
description: Google Gemini CLI code review with model flexibility and CI/CD integration
when-to-use: When user requests Gemini-powered code review or needs large-context review
user-invocable: true
effort: medium
---

# Google Gemini Code Review Skill


Use Google's Gemini CLI for code review. Run most reviews with a fast default model, and switch to a deep-reasoning model only when changes are complex (architecture-level changes, concurrency/state machines, security boundaries).

**Sources:** [Gemini CLI](https://github.com/google-gemini/gemini-cli) | [Code Review Extension](https://github.com/gemini-cli-extensions/code-review) | [Gemini Code Assist](https://codeassist.google/) | [GitHub Action](https://github.com/google-github-actions/run-gemini-cli)

---

## Why Gemini for Code Review?

| Feature | Benefit |
|---------|---------|
| **1M token context** | Entire repositories fit - no chunking needed |
| **Free tier** | 1,000 requests/day with Google account |
| **Consistent output** | Clean formatting, predictable structure |
| **GitHub native** | Gemini Code Assist app for auto PR reviews |

#
---

## Installation

### Prerequisites

```bash
# Check Node.js version (requires 20+)
node --version

# Install Node.js 20 if needed
# macOS
brew install node@20

# Or via nvm
nvm install 20
nvm use 20
```

### Install Gemini CLI

```bash
# Via npm (recommended)
npm install -g @google/gemini-cli

# Via Homebrew (macOS)
brew install gemini-cli

# Or run without installing
npx @google/gemini-cli

# Verify installation
gemini --version
```

### Install Code Review Extension

```bash
# Requires Gemini CLI v0.4.0+
gemini extensions install https://github.com/gemini-cli-extensions/code-review

# Verify extension
gemini extensions list
```

---

## Authentication

### Option 1: Gemini API Key

**Free tier: 100 requests/day**

```bash
# Get API key from https://aistudio.google.com/apikey

# Set environment variable
export GEMINI_API_KEY="your-api-key"

# Or add to shell profile
echo 'export GEMINI_API_KEY="your-api-key"' >> ~/.zshrc

# Run Gemini
gemini
```

### Option 2: Vertex AI (Enterprise)

```bash
# For Google Cloud projects
export GOOGLE_API_KEY="your-api-key"
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_PROJECT="your-project-id"

gemini
```

---

## Interactive Code Review

### Using the Code Review Extension

```bash
# Start Gemini CLI
gemini

# Run code review on current branch
/code-review
```

The extension analyzes:
- Code changes on your current branch
- Identifies quality issues
- Suggests fixes

### Manual Review Prompts

```bash
# In interactive mode
gemini

# Then ask:
> Review the changes in this branch for bugs and security issues
> Analyze src/api/users.ts for potential vulnerabilities
> What are the code quality issues in the last 3 commits?
```

---

## Headless Mode (Automation)

### Basic Usage

```bash
# Headless/non-interactive usage requires GEMINI_API_KEY (or Vertex AI).
# Interactive OAuth login is not supported in headless mode.

# Simple prompt execution
gemini -p "Review the code changes for bugs and security issues"

# With JSON output (for parsing)
gemini -p "Review the changes" --output-format json

# Stream JSON events (real-time)
gemini -p "Review and fix issues" --output-format stream-json

# Specify model explicitly when needed
gemini -m MODEL -p "Review this PR diff for correctness and code quality"
```

### Model Selection

- Most tasks: `gemini-3-flash-preview`
- Complex reasoning only (architecture/concurrency/state machines/security boundaries): `gemini-2.5-pro`

### Full CI/CD Example

```bash
# Get diff and review
git diff origin/main...HEAD > diff.txt

gemini -p "Review this code diff for:
1. Security vulnerabilities
2. Performance issues
3. Code quality problems
4. Missing error handling

Diff:
$(cat diff.txt)
" --output-format json > review.json
```

### Session Tracking

```bash
# Track token usage and costs
gemini -p "Review changes" --session-summary metrics.json

# View metrics
cat metrics.json
```

---

## GitHub Integration

### Option 1: Gemini Code Assist App (Easiest)

Install from [GitHub Marketplace](https://github.com/marketplace/gemini-code-assist):

1. Go to GitHub Marketplace → Gemini Code Assist
2. Click "Install" and select repositories
3. PRs automatically get reviewed when opened

**Commands in PR comments:**
```
/gemini review     # Request code review
/gemini summary    # Get PR summary
/gemini help       # Show available commands
```

**Quota:**
- Free: 33 PRs/day
- Enterprise: 100+ PRs/day

### Option 2: GitHub Action

```yaml
# .github/workflows/gemini-review.yml
name: Gemini Code Review

on:
  pull_request:
    types: [opened, synchronize]

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Install Gemini CLI
        run: npm install -g @google/gemini-cli

      - name: Run Review
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: |
          # Get diff
          git diff origin/${{ github.base_ref }}...HEAD > diff.txt

          # Run Gemini review
          gemini -p "Review this pull request diff for bugs, security issues, and code quality problems. Be specific about file names and line numbers.

          $(cat diff.txt)" > review.md

      - name: Post Review Comment
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const review = fs.readFileSync('review.md', 'utf8');
            github.rest.issues.createComment({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
              body: `## 🤖 Gemini Code Review\n\n${review}`
            });
```

### Option 3: Official GitHub Action

```yaml
# .github/workflows/gemini-review.yml
name: Gemini Code Review

on:
  pull_request:
    types: [opened, synchronize]
  issue_comment:
    types: [created]

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      issues: write

    steps:
      - uses: actions/checkout@v4

      - name: Run Gemini CLI
        uses: google-github-actions/run-gemini-cli@v1
        with:
          gemini_api_key: ${{ secrets.GEMINI_API_KEY }}
          prompt: "Review this pull request for code quality, security issues, and potential bugs."
```

**On-demand commands in comments:**
```
@gemini-cli /review
@gemini-cli explain this code change
@gemini-cli write unit tests for this component
```

---

## GitLab CI/CD

```yaml
# .gitlab-ci.yml
gemini-review:
  image: node:20
  stage: review
  script:
    - npm install -g @google/gemini-cli
    - |
      gemini -p "Review the merge request changes for bugs, security issues, and code quality" > review.md
    - cat review.md
  artifacts:
    paths:
      - review.md
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  variables:
    GEMINI_API_KEY: $GEMINI_API_KEY
```

---

## Configuration

### Global Config

```bash
# ~/.gemini/settings.json
{
  "model": "gemini-3-flash-preview",
  "theme": "dark",
  "sandbox": true
}
```

### Project Config (GEMINI.md)

Create a `GEMINI.md` file in your project root for project-specific context:

```markdown
# Project Context for Gemini

## Tech Stack
- TypeScript with strict mode
- React 18 with hooks
- FastAPI backend
- PostgreSQL database

## Code Review Focus Areas
1. Type safety - ensure proper TypeScript types
2. React hooks rules - check for dependency array issues
3. SQL injection - verify parameterized queries
4. Authentication - check all endpoints have proper auth

## Conventions
- Use camelCase for variables
- Use PascalCase for components
- All API errors should use AppError class
```

---

## CLI Quick Reference

```bash
# Interactive
gemini                          # Start interactive mode
/code-review                    # Run code review extension

# Headless
gemini -p "prompt"              # Single prompt, exit
gemini -p "prompt" --output-format json   # JSON output
gemini -m MODEL -p "prompt"     # Select model

# Extensions
gemini extensions list          # List installed
gemini extensions install URL   # Install extension
gemini extensions update        # Update all

# Key Flags
--output-format json            # Structured output
--output-format stream-json     # Real-time events
--session-summary FILE          # Track metrics
-m MODEL                        # Select model
```

---

## Comparison: Claude vs Codex vs Gemini

| Aspect | Claude | Codex CLI | Gemini CLI |
|--------|--------|-----------|------------|
| **Setup** | None (built-in) | npm + OpenAI API | npm + Google Account |
| **Model** | Claude | GPT-5.3-Codex | Gemini 2.5 Pro |
| **Context** | Conversation | Fresh per review | 1M tokens (huge!) |
| **Free Tier** | N/A | Limited | 1,000/day |
| **Best For** | Quick reviews | High accuracy | Large codebases |
| **GitHub Native** | No | @codex | Gemini Code Assist |

### When to Use Each

| Scenario | Recommended Engine |
|----------|-------------------|
| Quick in-flow review | Claude |
| Critical security review | Codex (88% detection) |
| Large codebase (100+ files) | Gemini (1M context) |
| Free automated reviews | Gemini |
| Multiple perspectives | All three (dual/triple engine) |

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `gemini: command not found` | `npm install -g @google/gemini-cli` |
| `Node.js version error` | Upgrade to Node.js 20+ |
| `Authentication failed` | Re-run `gemini` and re-authenticate |
| `OAuth login not available in CI/headless` | Use `GEMINI_API_KEY` (or Vertex AI) for automation |
| `Extension not found` | `gemini extensions install https://github.com/gemini-cli-extensions/code-review` |
| `Rate limited` | Wait or upgrade to Vertex AI |
| `Hangs in CI` | Ensure `DEBUG` env var is not set |

---

## Anti-Patterns

- **Skipping authentication setup** - Always configure before CI/CD
- **Using API key in logs** - Use secrets management
- **Ignoring context limits** - Even 1M tokens has limits for huge monorepos
- **Running on every commit** - Use on PRs only to save quota
- **Not setting project context** - Add GEMINI.md for better reviews

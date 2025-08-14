# Claude Configuration



## Git Worktree Workflow

When starting work on a feature, create a git worktree:
```bash
git worktree add ~/work/ai_workspaces/[meaningful-name] -b [meaningful-branch-name]
```

This creates an isolated workspace in the AI workspaces folder with a new branch for the feature.

## Note-Taking Locations

Choose an appropriate location for feature-specific notes:

- **Current directory**: `./dev/[feature_name]/` or `./notes/[feature_name]/`
- **Calmmage seasonal notes**:
  `~/work/projects/calmmage/experiments/[latest_season]/_notes/projects/[project_name]/[feature_name]/`

Use descriptive feature names (e.g., `auth_system`, `api_refactor`, `user_dashboard`). Create markdown files for task
tracking and project documentation in the chosen location.

## Three Main Scenarios

### Scenario 1: "simple"
- **Purpose**: Minimal overhead, no extra process
- **Action**: Cancel all additional instructions and workflows
- **Behavior**: Proceed without any extra clarifications, just as before
- **Context**: Plain development, zero ceremony

### Scenario 2: "new project"
- **Purpose**: Green field development in new directory
- **Prerequisites**:
    - Working in a new/empty directory
    - Empty repo or initialized template
- **Process**:
    1. Verify empty/clean environment
    2. Work with user to determine:
        - Project idea and goals
        - UI/interaction type (CLI tool, web interface, Telegram bot, utility library)
        - Sample data and usage scenarios
        - Main usage workflow
    3. Create stubs for future clarifications
    4. Ask clarifying questions about planned architecture
- **Notes**: May not need all details upfront - create placeholders for iterative refinement

### Scenario 3: "brownfield" (existing environment)
- **Purpose**: Working within existing codebase/repo on specific feature/improvement
- **Process**:
    1. **Determine working location**: Identify main project directory
    2. **Set up project notes**:
        - Find or create specialized notes folder for this specific feature/project
        - Structure: `experiments/season_4_jun_2025/_notes/projects/[project_name]/`
    3. **Task tracking setup**: Use Markdown files in the notes folder for task tracking
    4. **Documentation**:
        - Note project path, notes path, and description
        - Add entry to `outstanding_ideas.md` in appropriate section/inbox
    5. **Context gathering**: Understand existing architecture and integration points
- **Goal**: Structured approach to extending/improving existing systems

# Calmmage Ecosystem
- **botspot**: Telegram bot framework with routing and middleware
  - Location: `~/work/projects/botspot/`
  - Import: `from botspot import get_chat_fetcher, llm_provider, commands_menu`
  - Usage: Component-based architecture with send_safe, chat_binder, user_interactions
- **calmlib**: Personal utility library with read/write, logging, service registry
  - Location: `~/work/projects/calmmage/calmlib/`
  - Import: Look around and see what's available at runtime - structure may be updated
  - Usage: Various python utils for file operations, logging, service management
- **tools**: Collection of CLI utilities and automation tools
  - Location: `~/work/projects/calmmage/tools/` with subdirectories for each tool
  - Import: `from tools.tool_name.module import Class`
  - Usage: `uv run typer ~/work/projects/calmmage/tools/tool_name/cli.py run [command]`
- **docker**: Containerization for local services and deployment
  - Location: Local Docker Desktop installation
  - Usage: `docker run -d --name mongodb mongo:latest`, containers accessible on localhost
- **mongodb**: Document database for data storage and querying
  - Location: localhost MongoDB via Docker
  - Usage: Connection string from ~/.env, accessible through botspot mongo_database component
- **scripts**: Scheduled jobs and automation scripts
  - Location: `~/work/projects/calmmage/scripts/scheduled_tasks/` and `~/work/projects/calmmage/scripts/cronicle/`
  - Usage: Jobs report status via `🎯 FINAL STATUS:` and `📝 FINAL NOTES:` format
- **~/.env**: Environment variables via planned calmlib env key discovery
  - Location: `~/.env` file in user home directory
  - Usage: dotenv loading, planned calmlib utilities for key discovery and management
- **cronicle**: Job scheduler for automated tasks and workflows
  - Location: `~/work/projects/calmmage/tools/cronicle_scheduler/cli/cronicle_manager.py`
  - Usage: `uv run typer ~/work/projects/calmmage/tools/cronicle_scheduler/cli/cronicle_manager.py run [command]`
- **cronitor**: Health monitoring and alerting for scheduled jobs
  - Location: `~/work/projects/calmmage/scripts/cronicle/cronitor_ping.py`
  - Usage: HTTP pings to cronitor.io for job health monitoring
- **telegram-downloader**: Message download, parsing, and processing ecosystem
  - Location: `~/work/projects/calmmage/tools/telegram_downloader/`
  - Usage: Downloads telegram messages to local MongoDB via Docker, stores in structured format with chat/user metadata
- **obsidian-ecosystem**: Note management with database-like access to people/contacts, bookmarks, posts/blog/zettelkasten fields
  - Location: `~/work/projects/calmmage/tools/obsidian_sorter/` for sorting automation
  - Usage: Database-like access to Obsidian vault with structured data fields for contacts, bookmarks, content
- **nix-config**: System configuration with tool aliases and environment setup
  - Location: `~/work/projects/calmmage/config/nix/` with aliases in `shell/aliases/` subdirectory
  - Usage: Shell aliases that link calmmage tools with typer commands, see alias definitions for tool access patterns

# Python Execution Requirements

**Always use uv for Python command execution**

**For running Python scripts:**
```bash
uv run python script.py
```

**For running Typer CLI tools:**
```bash
uv run typer path/to/cli.py run [command] [args]
```

**Examples:**
- `uv run python script.py`
- `uv run typer path/to/cli.py run [command]`

**Never use bare python or direct script execution - always prefix with `uv run`**

**Use absolute imports instead of sys.path.append()**
- Prefer direct imports when possible: `from module_name.file import Class`
- Avoid adding paths manually with `sys.path.append()`

# Python Libraries
- **pathlib**: File system path handling
- **dotenv**: Loads `.env` variables
- **requests**: HTTP requests for APIs
- **loguru**: Colorful, easy logging
- **typer**: Modern CLI with type hints
- **rich**: Enhanced terminal output (tables, colors)
- **fastapi**: Fast web APIs with async
- **fastui**: Declarative web UIs for FastAPI
- **pydantic**: Data validation with type hints
- **tqdm**: Progress bars for loops

# Current Shell Aliases

```bash
aa=add_alias
add_cronicle='typer ~/calmmage/tools/cronicle_scheduler/cli/cronicle_manager.py run create'
architect='~/calmmage/tools/ai_character_launcher/launcher.sh SoftwareArchitect'
architect-gemini='~/calmmage/tools/ai_character_launcher/launcher.sh SoftwareArchitect gemini'
at=add_tool
bump='poetry version patch'
bump-major='poetry version major'
bump-minor='poetry version minor'
cat1=bat
contrarian='~/calmmage/tools/ai_character_launcher/launcher.sh Contrarian'
contrarian-gemini='~/calmmage/tools/ai_character_launcher/launcher.sh Contrarian gemini'
cp1='rsync -ah --progress'
cpa=copy_absolute_path
cronicle_jobs='typer ~/calmmage/tools/cronicle_scheduler/cli/cronicle_manager.py run list'
cz='cursor ~/.zshrc'
czc='cursor ~/.zshrc.custom'
czl='cursor ~/.zshrc.local'
deploy_ai_prompts='typer ~/calmmage/tools/ai_instructions_composer/cli.py run deploy --tool claude --tool cursor --tool gemini --no-interactive'
df1=duf
diff1=delta
dipru='docker image prune -a'
dps='docker ps'
dpsa='docker ps -a'
drm!='docker container rm -f'
find1=fd
fix_repo='typer ~/calmmage/tools/repo_fixer/repo_fixer.py run'
fp='typer ~/calmmage/tools/project_discoverer/pd_cli.py run'
fp_=find_project
free1=bottom
git-sync='uv run typer tools/git_sync_tool/cli.py run'
grep1=rg
gsync='uv run typer tools/git_sync_tool/cli.py run sync-all'
hetzner='ssh root@$HETZNER_SERVER_IP'
hetzner-ef='ssh root@$HETZNER_EF_SERVER_IP'
hetzner-old='ssh root@$HETZNER_OLD_SERVER_IP'
ipython='~/calmmage/.venv/bin/ipython'
kgnosl='kubectl get nodes --show-labels'
kgpsl='kubectl get pods --show-labels'
kill1=fkill
less1=most
lj='typer ~/calmmage/tools/local_job_runner/cli.py run list'
lnsafe='runp ~/calmmage/tools/lnsafe.py'
locate1=plocate
mva=move_and_link
netstat1=ss
new_job='typer ~/calmmage/tools/cronicle_scheduler/cli/cronicle_manager.py run create'
nf='typer ~/calmmage/tools/project_manager/pm_cli.py run new-feature'
nixfast='darwin-rebuild switch --offline --impure --flake $CALMMAGE_DIR/config/nix/.#$USER'
nixnix='nix flake update; darwin-rebuild switch --flake .#$USER'
nixswitch='darwin-rebuild switch --impure --flake $CALMMAGE_DIR/config/nix/.#$USER'
nixup='pushd $CALMMAGE_DIR/config/nix; git stash; git pull; git stash pop; nix flake update; nixswitch; popd'
nmp='typer ~/calmmage/tools/project_manager/pm_cli.py run new-mini-project'
np='typer ~/calmmage/tools/project_manager/pm_cli.py run new-project'
nt='typer ~/calmmage/tools/project_manager/pm_cli.py run new-todo'
pad='poetry add'
pbld='poetry build'
pch='poetry check'
pcmd='poetry list'
pconf='poetry config --list'
pexp='poetry export --without-hashes > requirements.txt'
pin='poetry init'
pinst='poetry install'
plck='poetry lock'
pm='typer ~/calmmage/tools/project_manager/pm_cli.py run'
pnew='poetry new'
ppath='poetry env info --path'
pplug='poetry self show plugins'
ppub='poetry publish'
prm='poetry remove'
prun='poetry run'
ps1=procs
psad='poetry self add'
psh='poetry shell'
pshw='poetry show'
pslt='poetry show --latest'
psup='poetry self update'
psync='poetry install --sync'
ptree='poetry show --tree'
pup='poetry update'
pvinf='poetry env info'
pvoff='poetry config virtualenvs.create false'
pvrm='poetry env remove'
pvu='poetry env use'
rj='typer ~/calmmage/tools/local_job_runner/cli.py run run'
run_startup_jobs='typer ~/calmmage/tools/local_job_runner/cli.py run run'
runp=run_with_poetry
secretary='~/calmmage/tools/ai_character_launcher/launcher.sh Secretary'
secretary-gemini='~/calmmage/tools/ai_character_launcher/launcher.sh Secretary gemini'
sed1=sd
sort_projects='typer ~/calmmage/tools/project_arranger/cli.py run sort'
start_cronicle='/opt/cronicle/bin/control.sh start'
sz='subl ~/.zshrc'
szc='subl ~/.zshrc.custom'
szl='subl ~/.zshrc.local'
traceroute1=mtr
tree1=broot
typer='~/calmmage/.venv/bin/typer'
uvup='uv sync --upgrade --group test --group extras --group dev --group docs'
```

**Note**: Many tools also have Makefiles in their directories with usage examples - check for `Makefile` when using typer CLI tools.


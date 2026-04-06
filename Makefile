# ══════════════════════════════════════════════════════════════════════════════
# IAM Lab — Production Operations
# ══════════════════════════════════════════════════════════════════════════════
SHELL := /bin/bash
.DEFAULT_GOAL := help

# ── Setup ─────────────────────────────────────────────────────────────────────

.PHONY: setup
setup: certs env ## First-time setup: generate certs + create .env from template
	@echo ""
	@echo "Setup complete. Edit .env with your secrets, then run: make up"

.PHONY: certs
certs: ## Generate TLS certificates (CA + server with SANs)
	@bash certs/generate-certs.sh

.PHONY: env
env: ## Create .env from .env.example (skips if .env exists)
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "[+] Created .env from .env.example — edit secrets before starting"; \
	else \
		echo "[=] .env already exists — skipping"; \
	fi

# ── Stack Lifecycle ───────────────────────────────────────────────────────────

.PHONY: up
up: ## Start the full IAM stack (12 containers)
	docker compose up -d
	@echo ""
	@echo "Stack starting. Run 'make health' to verify."

.PHONY: down
down: ## Stop all containers (preserves volumes)
	docker compose down

.PHONY: restart
restart: down up ## Restart the full stack

.PHONY: clean
clean: ## Full teardown: stop containers + remove all volumes
	docker compose down -v
	@echo "All containers and volumes removed."

.PHONY: pull
pull: ## Pull latest images for all services
	docker compose pull

.PHONY: build
build: ## Build custom images (siem-receiver, siem-forwarder)
	docker compose build

# ── Monitoring ────────────────────────────────────────────────────────────────

.PHONY: health
health: ## Run production readiness healthcheck (7 assertions)
	@bash scripts/healthcheck.sh

.PHONY: logs
logs: ## Tail logs from all containers
	docker compose logs -f --tail=50

.PHONY: logs-kc
logs-kc: ## Tail Keycloak logs only
	docker compose logs -f --tail=100 keycloak

.PHONY: status
status: ## Show container status with health and resource usage
	@docker compose ps
	@echo ""
	@docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"

# ── Operations ────────────────────────────────────────────────────────────────

.PHONY: backup
backup: ## Backup PostgreSQL + LDAP data with 30-day retention
	@bash scripts/backup.sh

.PHONY: restore
restore: ## Restore from most recent backup (interactive)
	@bash scripts/restore.sh

.PHONY: ldap-search
ldap-search: ## Verify LDAP users are loaded
	@docker exec $$(docker ps -qf "name=openldap") \
		ldapsearch -x -H ldap://localhost:389 \
		-b "ou=users,dc=rbclab,dc=local" -D "cn=admin,dc=rbclab,dc=local" \
		-w "$${LDAP_ADMIN_PASSWORD}" "(objectClass=inetOrgPerson)" uid cn mail 2>/dev/null \
		|| echo "LDAP search failed — is OpenLDAP running?"

# ── IGA Automation ────────────────────────────────────────────────────────────

.PHONY: certify
certify: ## Run access certification report (ISO 27001 / SOX)
	python3 scripts/iam_lifecycle.py certify --days 90

.PHONY: jit-list
jit-list: ## List active JIT privileged access grants
	python3 scripts/jit_access.py list

.PHONY: jit-expire
jit-expire: ## Expire all JIT grants past their window
	python3 scripts/jit_access.py expire

# ── Testing ───────────────────────────────────────────────────────────────────

.PHONY: test
test: ## Run integration tests against live stack
	pip install -q -r tests/requirements.txt
	pytest tests/ -v --tb=short

.PHONY: lint
lint: ## Lint all Python scripts
	flake8 scripts/*.py siem-receiver/app.py siem-forwarder/siem_forwarder.py \
		--max-line-length=120 --ignore=E501,W503
	@echo "Lint: PASS"

.PHONY: validate
validate: ## Validate all configuration files
	@echo "── Docker Compose ──"
	@docker compose config --quiet && echo "  OK"
	@echo "── Nginx ──"
	@docker run --rm -v "$$(pwd)/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
		nginx:1.27-alpine nginx -t 2>&1
	@echo "── Grafana Dashboard JSON ──"
	@for f in grafana/dashboards/*.json; do \
		python3 -c "import json; json.load(open('$$f')); print('  OK: $$f')"; \
	done
	@echo "── Promtail Config ──"
	@python3 -c "import yaml; yaml.safe_load(open('monitoring/promtail-config.yml')); print('  OK')"
	@echo "── Python Syntax ──"
	@python3 -m py_compile scripts/iam_lifecycle.py && echo "  OK: iam_lifecycle.py"
	@python3 -m py_compile scripts/jit_access.py && echo "  OK: jit_access.py"
	@python3 -m py_compile scripts/siem_forwarder.py && echo "  OK: siem_forwarder.py"
	@python3 -m py_compile siem-receiver/app.py && echo "  OK: siem-receiver/app.py"
	@python3 -m py_compile siem-forwarder/siem_forwarder.py && echo "  OK: siem-forwarder/siem_forwarder.py"
	@echo "── Bash Syntax ──"
	@bash -n scripts/healthcheck.sh && echo "  OK: healthcheck.sh"
	@bash -n scripts/backup.sh && echo "  OK: backup.sh"
	@bash -n scripts/restore.sh && echo "  OK: restore.sh"
	@bash -n certs/generate-certs.sh && echo "  OK: generate-certs.sh"
	@bash -n ldap/bootstrap.sh && echo "  OK: bootstrap.sh"
	@echo ""
	@echo "All validations passed."

# ── Terraform ─────────────────────────────────────────────────────────────────

.PHONY: tf-init
tf-init: ## Initialize Terraform (Keycloak IaC)
	cd terraform && terraform init

.PHONY: tf-plan
tf-plan: ## Plan Terraform changes
	cd terraform && terraform plan

.PHONY: tf-apply
tf-apply: ## Apply Terraform configuration to Keycloak
	cd terraform && terraform apply

# ── Help ──────────────────────────────────────────────────────────────────────

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

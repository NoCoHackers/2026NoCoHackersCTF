# NoCo Hackers CTF 2026 - top-level developer entry point.
#
# The whole event on your laptop:
#   make dev        build everything, bring up CTFd + Traefik + every challenge
#   make dev-urls   print where to reach it all
#   make dev-down   tear it down (add CLEAN=1 to drop CTFd's database too)
#
# Individual pieces still work standalone; see AGENTS.md.

DEV_NET     := noco-dev-edge
DEV_PROJECT := noco-dev
DEV         := docker compose -p $(DEV_PROJECT) \
                 -f deploy/dev/compose.infra.yml \
                 -f deploy/dev/docker-compose.dev.yml \
                 --env-file deploy/dev/flags.env

.PHONY: help dev dev-build dev-up dev-down dev-logs dev-ps dev-urls dev-hosts dev-smoke sync domains \
        validate test-all base-images

help:  ## show this help
	@grep -E '^[a-zA-Z-]+:.*?##' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

# ---- local dev environment --------------------------------------------------
dev: base-images ## build + run the ENTIRE environment locally
	@docker network inspect $(DEV_NET) >/dev/null 2>&1 || docker network create $(DEV_NET)
	@deploy/chals/generate.py --dev
	@deploy/dev/gen-flags.sh
	@$(DEV) up -d --build --remove-orphans
	@echo
	@$(MAKE) --no-print-directory dev-urls

dev-up: ## start the dev stack without rebuilding
	@$(DEV) up -d

dev-smoke: ## verify a running dev stack routes everything (make dev first)
	@tools/dev-smoke.sh

dev-down: ## stop the dev stack (CLEAN=1 also removes volumes/DB)
	@$(DEV) down $(if $(CLEAN),-v,)
	@docker network rm $(DEV_NET) 2>/dev/null || true

dev-logs: ## tail dev logs; make dev-logs S=web-haunted-brewery for one
	@$(DEV) logs -f --tail=80 $(S)

dev-ps: ## what's running locally
	@$(DEV) ps

dev-urls: ## print the local URLs
	@echo "Local environment (plain HTTP):"
	@echo "  Scoreboard   http://ctf.localhost"
	@echo "  Traefik UI   http://localhost:8081"
	@printf "  Web chals    "; \
	  grep -ho 'Host(`[^`]*`)' deploy/dev/docker-compose.dev.yml | \
	  sed 's/Host(`/http:\/\//;s/`)//' | paste -sd' ' - ; \
	  test -s deploy/dev/docker-compose.dev.yml || echo "(run make dev first)"
	@printf "  TCP chals    "; \
	  grep -hoE '[0-9]{5}:1337' deploy/dev/docker-compose.dev.yml | \
	  sed 's|:1337|| ; s|^|nc localhost |' | paste -sd', ' - ; true

dev-hosts: ## print /etc/hosts lines (only if *.localhost doesn't resolve for you)
	@echo "# NoCo dev - add to /etc/hosts only if *.localhost isn't already resolving"
	@echo "127.0.0.1 ctf.localhost traefik.localhost"
	@grep -ho 'Host(`[^`]*`)' deploy/dev/docker-compose.dev.yml 2>/dev/null | \
	  sed 's/Host(`//;s/`)//' | sort -u | sed 's/^/127.0.0.1 /'

# ---- the same checks CI runs ------------------------------------------------
domains: ## regenerate deploy/domains.env + challenge routes from event.yml
	@tools/domains.py --env
	@deploy/chals/generate.py

sync: ## push challenges + event config to CTFd (TARGET=dev for local; needs CTFCLI_ACCESS_TOKEN)
	@deploy/scoreboard/sync.sh $(if $(filter dev,$(TARGET)),--dev,)

base-images: ## build the three base images
	@tools/build-base-images.sh

validate: ## validate every challenge manifest
	@tools/validate.py

test-all: base-images ## build+boot+autosolve every challenge (what CI does)
	@find challenges -name challenge.yml -not -path '*/TEMPLATE/*' -printf '%h\n' | \
	  sort -u | while read -r d; do tools/test-challenge.sh "$$d" || exit 1; done

# Challenge-host operations. Run from the repo root on the challenge VPS.
COMPOSE = docker compose -f compose.traefik.yml -f docker-compose.generated.yml \
          --env-file ../domains.env --env-file flags.env

.PHONY: help init generate check up down restart logs ps pull reset-one
help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | column -t -s "$$(printf '\t')"

init:        ## one-time: create the shared edge network
	docker network inspect noco-edge >/dev/null 2>&1 || docker network create noco-edge

generate:    ## regenerate docker-compose.generated.yml from challenges/
	./generate.py

check:       ## fail if the generated compose is stale (CI)
	./generate.py --check

flags.env:   ## decrypt the flag file (needs the age key on this host)
	sops -d flags.enc.env > flags.env && chmod 600 flags.env

up: init flags.env  ## pull and start everything
	$(COMPOSE) pull
	$(COMPOSE) up -d --remove-orphans

down:        ## stop everything (scoreboard is a separate host and unaffected)
	$(COMPOSE) down

ps:          ## what's running and healthy
	$(COMPOSE) ps

logs:        ## tail everything; make logs S=web-haunted-brewery for one
	$(COMPOSE) logs -f --tail=100 $(S)

restart:     ## restart one challenge: make restart S=web-haunted-brewery
	$(COMPOSE) restart $(S)

reset-one:   ## nuke and recreate one challenge's container and state
	$(COMPOSE) rm -sf $(S) && $(COMPOSE) up -d $(S)

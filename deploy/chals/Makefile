# Challenge-host operations. Run from the repo root on the challenge VPS.
COMPOSE = docker compose -f compose.traefik.yml -f docker-compose.generated.yml \
          --env-file ../domains.env --env-file flags.env
EDGE_SUBNET = 172.30.0.0/24
TCP_SUBNET  = 172.31.0.0/24

.PHONY: help init generate check up down restart logs ps pull reset-one
help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | column -t -s "$$(printf '\t')"

init:        ## one-time: create and verify the production challenge networks
	@set -eu; \
	if docker network inspect noco-edge >/dev/null 2>&1; then \
	  test "$$(docker network inspect -f '{{.Internal}}' noco-edge)" = true || { \
	    echo 'FATAL: noco-edge permits egress; remove it after stopping the stack, then rerun init' >&2; exit 1; }; \
	else \
	  docker network create --internal --subnet $(EDGE_SUBNET) noco-edge >/dev/null; \
	fi; \
	if docker network inspect noco-isolated >/dev/null 2>&1; then \
	  test "$$(docker network inspect -f '{{(index .IPAM.Config 0).Subnet}}' noco-isolated)" = '$(TCP_SUBNET)' || { \
	    echo 'FATAL: noco-isolated has the wrong subnet; rerun deploy/host/bootstrap.sh chals' >&2; exit 1; }; \
	  test "$$(docker network inspect -f '{{index .Options "com.docker.network.bridge.enable_icc"}}' noco-isolated)" = false || { \
	    echo 'FATAL: noco-isolated permits lateral traffic; stop the stack, remove that network, then rerun init' >&2; exit 1; }; \
	else \
	  docker network create --subnet $(TCP_SUBNET) \
	    --opt com.docker.network.bridge.enable_icc=false noco-isolated >/dev/null; \
	fi

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

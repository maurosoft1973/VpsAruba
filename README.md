# VpsAruba

Provisioning di un VPS (Cloud Server) su **Aruba Cloud** con **Pulumi** e configurazione con **Ansible**, il tutto da una GitHub Action.

| Cosa | Dove |
|---|---|
| Workflow di provisioning + configurazione | `.github/workflows/provision.yml` |
| Workflow di distruzione | `.github/workflows/destroy.yml` |
| Infrastruttura (Pulumi, Python) | `infra/` |
| Configurazione server (Ansible) | `ansible/` |

## Cosa fa

1. **Pulumi** crea progetto, VPC, subnet, security group (22/80/443 in ingresso), Elastic IP, disco di boot e Cloud Server.
   Non esiste un provider Pulumi nativo per Aruba: si usa il provider Terraform ufficiale
   [`arubacloud/arubacloud`](https://github.com/Arubacloud/terraform-provider-arubacloud) tramite
   [Any Terraform Provider](https://www.pulumi.com/docs/iac/concepts/providers/any-terraform-provider/);
   l'SDK Python viene generato a ogni run da `pulumi package add`.
2. **Ansible** (ruoli in `ansible/roles/`):
   - `base_users`: crea i 2 utenti richiesti in input (sudo, chiave SSH, lingering per i container rootless) e rende sshd key-only senza login root.
   - `podman`: installa Podman, abilita `podman.socket`, crea la rete `traefik`.
   - `traefik`: Traefik v3 in Podman (unit systemd) su 80/443, redirect HTTP→HTTPS e **certificato wildcard** `domain` + `*.domain` con Let's Encrypt tramite DNS-01. Traefik rinnova il certificato da solo; il playbook attende l'emissione e, se fallisce, stampa i log.

Il workflow è idempotente: rilanciarlo riallinea l'infrastruttura e la configurazione senza ricreare il server.

## Setup (una volta)

Secret del repository (*Settings → Secrets and variables → Actions*):

| Secret | Contenuto |
|---|---|
| `PULUMI_ACCESS_TOKEN` | Token di Pulumi Cloud (conserva lo stato) |
| `ARUBACLOUD_CLIENT_ID` / `ARUBACLOUD_CLIENT_SECRET` | Credenziali API OAuth2 di Aruba Cloud |
| `DEPLOY_SSH_PRIVATE_KEY` | Chiave privata SSH dedicata al deploy (la pubblica viene derivata e iniettata nel server) |
| `DNS_PROVIDER_ENV` | Credenziali del provider DNS, una `CHIAVE=valore` per riga, es. `CF_DNS_API_TOKEN=...` |

Il certificato wildcard richiede la DNS-01 challenge, quindi il dominio deve essere gestito da un provider DNS
[supportato da lego](https://go-acme.github.io/lego/dns/) (Cloudflare, Route53, OVH, ...). Il codice del provider va
in input `dns_provider`, le variabili da mettere in `DNS_PROVIDER_ENV` sono nella pagina lego del provider.

## Uso

*Actions → Provision VPS Aruba → Run workflow*. Input principali: `domain`, `acme_email`, `dns_provider`,
nome e chiave pubblica SSH dei due utenti, `acme_staging` (usa la CA di staging, consigliato per il primo giro).
Alla fine l'IP pubblico è nel summary: crea i record DNS `domain` e `*.domain` verso quell'IP.

Per eliminare tutto: *Destroy VPS Aruba*, riscrivendo il nome dello stack per confermare.

## Note

- **Non testato su Aruba reale**: validati solo lint (ansible-lint profilo `production`, actionlint, yamllint), syntax-check Ansible e rendering dei template. Pulumi non era installabile nell'ambiente di sviluppo, quindi il primo run reale è il vero collaudo: il punto più fragile è `pulumi package add` e i nomi delle classi generate (`pulumi_arubacloud.Cloudserver`, ecc.).
- Immagine, flavor, location e zona hanno i default dell'esempio ufficiale (`LU22-001`, `CSO4A8`, `ITBG-Bergamo`/`ITBG-1`); gli ID validi sono nelle [metadata API](https://api.arubacloud.com/docs/metadata/). Ubuntu 22.04 ha Podman 3.4: se trovi l'ID di un'immagine Ubuntu 24.04 conviene usarla.
- La porta 22 è aperta a `0.0.0.0/0` di default perché i runner GitHub hanno IP variabile; sshd è comunque key-only.
- Traefik legge i container **rootful** dalla rete `traefik` (via `podman.socket`). I container rootless degli utenti non sono visibili al socket di root: si pubblicano su una porta locale e si espongono con un file in `/opt/traefik/dynamic/`.
- Il provider Terraform è fissato a `0.3.0` (default in `.github/actions/pulumi-setup/action.yml`).

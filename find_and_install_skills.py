#!/usr/bin/env python3
"""
find_and_install_skills.py

Busca Claude/OpenCode Skills (carpetas con SKILL.md) publicadas en GitHub
que coincidan con tus keywords, y las descarga tal cual a tu carpeta de
skills. Este script NO trae contenido de skills embebido: todo lo que se
instala viene de repos reales en GitHub.

Como busca:
  1. Descubrimiento (GitHub Search API):
     - busca codigo: archivos "SKILL.md" cuyo contenido/ruta mencione tus
       keywords (requiere token para no chocar con el rate limit).
     - busca repositorios: repos cuyo nombre/descripcion/topics matcheen
       tus keywords (para despues escanear TODO el repo en busca de skills).
  2. Descarga (codeload.github.com, sin rate limit de la API):
     - para cada repo candidato, baja el tarball completo y copia las
       carpetas que contienen un SKILL.md matcheado.

Uso:
  python3 find_and_install_skills.py spring "spring boot" "spring data jpa" "spring security"
  python3 find_and_install_skills.py --dest /ruta/a/tus/skills spring angular
  python3 find_and_install_skills.py --repo tuorg/tus-skills spring   # ademas escanea ese repo puntual
  GITHUB_TOKEN=ghp_xxx python3 find_and_install_skills.py spring      # recomendado, evita rate limits

Sin GITHUB_TOKEN, la busqueda amplia (Search API) puede fallar por rate
limit (10 req/min); el script lo informa y sigue con lo que haya
encontrado o con los repos pasados por --repo.
"""

import argparse
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

# MODO DE USO
# export GITHUB_TOKEN=ghp_
# python3 find_and_install_skills.py \
#  "spring boot" "spring data jpa" "spring security" \
#  "spring cloud" "spring webflux" "hibernate" \
#  "lombok" "flyway" "postgresql" "redis" "docker"

DEFAULT_DEST = os.path.expanduser("~/.config/opencode/skills")
GITHUB_API = "https://api.github.com"


def gh_headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "find-and-install-skills",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def gh_get_json(url: str):
    req = urllib.request.Request(url, headers=gh_headers())
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        try:
            msg = json.loads(body).get("message", "")
        except json.JSONDecodeError:
            msg = body[:200]
        print(f"   [GitHub API] {e.code} en {url} -> {msg}")
        return None
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"   [GitHub API] error de red en {url} -> {e}")
        return None


# ---------------------------------------------------------------------------
# Etapa 1: descubrimiento via GitHub Search API
# ---------------------------------------------------------------------------

def search_code_for_skill_md(keyword: str) -> set:
    """Busca archivos SKILL.md cuyo contenido mencione la keyword.
    Devuelve un set de 'owner/repo' candidatos."""
    q = urllib.parse.quote(f"filename:SKILL.md {keyword}")
    url = f"{GITHUB_API}/search/code?q={q}&per_page=20"
    data = gh_get_json(url)
    repos = set()
    if data and "items" in data:
        for item in data["items"]:
            repo_full_name = item.get("repository", {}).get("full_name")
            if repo_full_name:
                repos.add(repo_full_name)
    return repos


def search_repos_for_keyword(keyword: str) -> set:
    """Busca repositorios cuyo nombre/descripcion/topics matcheen la
    keyword combinada con 'skill' o 'claude'. Devuelve set de 'owner/repo'."""
    q = urllib.parse.quote(f"{keyword} skill in:name,description,topics")
    url = f"{GITHUB_API}/search/repositories?q={q}&per_page=10&sort=stars"
    data = gh_get_json(url)
    repos = set()
    if data and "items" in data:
        for item in data["items"]:
            full_name = item.get("full_name")
            if full_name:
                repos.add(full_name)
    return repos


def discover_candidate_repos(keywords: list, extra_repos: list) -> list:
    candidates = set(extra_repos)
    for kw in keywords:
        print(f"-> Buscando en GitHub (code search): SKILL.md + '{kw}'")
        found_code = search_code_for_skill_md(kw)
        candidates |= found_code
        time.sleep(1)  # cortesia con el rate limit

        print(f"-> Buscando en GitHub (repo search): repos de '{kw} skill'")
        found_repos = search_repos_for_keyword(kw)
        candidates |= found_repos
        time.sleep(1)

    return sorted(candidates)


# ---------------------------------------------------------------------------
# Etapa 2: descarga completa del repo (codeload, sin rate limit de API)
# ---------------------------------------------------------------------------

def download_repo_tarball(repo: str, workdir: str):
    """Descarga y extrae el tarball de un repo (main o master).
    Devuelve la carpeta extraida, o None si fallo."""
    for branch in ("main", "master"):
        url = f"https://codeload.github.com/{repo}/tar.gz/refs/heads/{branch}"
        req = urllib.request.Request(url, headers={"User-Agent": "find-and-install-skills"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            continue

        tarball_path = os.path.join(workdir, repo.replace("/", "_") + ".tar.gz")
        with open(tarball_path, "wb") as f:
            f.write(data)

        extract_dir = os.path.join(workdir, repo.replace("/", "_"))
        os.makedirs(extract_dir, exist_ok=True)
        try:
            with tarfile.open(tarball_path) as tar:
                members = tar.getmembers()
                for m in members:
                    parts = m.name.split("/", 1)
                    m.name = parts[1] if len(parts) > 1 else parts[0]
                tar.extractall(extract_dir, members=[m for m in members if m.name])
        except tarfile.TarError as e:
            print(f"   No se pudo extraer {repo}: {e}")
            return None
        return extract_dir
    return None


def find_matching_skill_dirs(extract_dir: str, keywords: list) -> dict:
    """Recorre el repo extraido buscando carpetas con SKILL.md cuyo nombre
    o contenido matchee alguna keyword (palabra completa). Devuelve
    {skill_name: path}."""
    kw_patterns = [re.compile(r"\b" + re.escape(k.lower()) + r"\b") for k in keywords]
    matches = {}

    for root, _, files in os.walk(extract_dir):
        if "SKILL.md" not in files:
            continue
        skill_name = os.path.basename(root)
        skill_md_path = os.path.join(root, "SKILL.md")
        try:
            with open(skill_md_path, encoding="utf-8", errors="ignore") as f:
                content_lower = f.read().lower()
        except OSError:
            content_lower = ""
        name_lower = skill_name.lower()

        if any(p.search(name_lower) or p.search(content_lower) for p in kw_patterns):
            matches[skill_name] = root

    return matches


# ---------------------------------------------------------------------------
# Instalacion
# ---------------------------------------------------------------------------

def install_skill(name: str, src_dir: str, dest: str) -> bool:
    dest_dir = os.path.join(dest, name)
    if os.path.exists(dest_dir):
        print(f"   (ya existe, no se sobreescribe) {name}")
        return False
    shutil.copytree(src_dir, dest_dir)
    return True


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Busca skills (SKILL.md) en GitHub para tus keywords y las descarga a tu carpeta de skills."
    )
    parser.add_argument("keywords", nargs="*", help="Keywords a buscar, ej: spring \"spring boot\" \"spring data jpa\"")
    parser.add_argument("--dest", default=DEFAULT_DEST, help=f"Carpeta destino (default: {DEFAULT_DEST})")
    parser.add_argument("--repo", action="append", default=[], help="Repo org/repo a escanear ademas de los encontrados (repetible)")
    parser.add_argument("--skip-search", action="store_true", help="No usar la Search API, solo escanear los --repo indicados")
    args = parser.parse_args()

    if not args.keywords and not args.repo:
        parser.print_help()
        return 1

    dest = os.path.abspath(os.path.expanduser(args.dest))
    os.makedirs(dest, exist_ok=True)
    keywords = args.keywords

    if not os.environ.get("GITHUB_TOKEN"):
        print(
            "Aviso: no hay GITHUB_TOKEN en el entorno. La busqueda amplia en GitHub\n"
            "(Search API) tiene un limite de 10 requests/minuto sin autenticar y\n"
            "puede fallar. Para mejores resultados:\n"
            "  export GITHUB_TOKEN=ghp_xxx   (un Personal Access Token sin permisos especiales alcanza)\n"
        )

    print(f"Destino: {dest}")
    print(f"Keywords: {keywords}\n")

    if args.skip_search:
        candidate_repos = list(args.repo)
        print("Busqueda amplia omitida (--skip-search); solo se escanean --repo indicados.\n")
    else:
        candidate_repos = discover_candidate_repos(keywords, args.repo)

    if not candidate_repos:
        print("No se encontraron repos candidatos (ni via busqueda ni via --repo).")
        print("Prueba con GITHUB_TOKEN configurado, o pasa repos puntuales con --repo org/repo.")
        return 0

    print(f"\nRepos candidatos a revisar ({len(candidate_repos)}):")
    for r in candidate_repos:
        print(f"  - {r}")
    print()

    installed = []
    with tempfile.TemporaryDirectory() as workdir:
        for repo in candidate_repos:
            print(f"-> Descargando y escaneando: {repo}")
            extract_dir = download_repo_tarball(repo, workdir)
            if not extract_dir:
                print(f"   No se pudo descargar {repo} (repo privado, invalido, o sin red). Saltando.")
                continue

            matches = find_matching_skill_dirs(extract_dir, keywords)
            if not matches:
                print("   Sin carpetas SKILL.md que matcheen las keywords en este repo.")
                continue

            for name, src_dir in matches.items():
                if install_skill(name, src_dir, dest):
                    installed.append((name, repo))
                    print(f"   Instalada: {name}  (de {repo})")

    print("\n== Resumen ==")
    if installed:
        for name, repo in installed:
            print(f"  - {name}  <-  {repo}")
        print(f"\nInstaladas en: {dest}")
    else:
        print("No se instalo ninguna skill nueva. Puede que no exista contenido publico")
        print("para estas keywords todavia, o que el rate limit de GitHub haya bloqueado")
        print("la busqueda (proba con GITHUB_TOKEN configurado).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
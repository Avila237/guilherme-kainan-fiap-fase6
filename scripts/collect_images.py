"""Coleta e montagem do dataset da Fase 6 (vaca x cachorro) a partir do Openverse (fotos CC do Flickr).

Uso:
    python3 collect_images.py coco-ids   # baixa as anotações do COCO e extrai os IDs Flickr (uma vez, ~250 MB)
    python3 collect_images.py download   # baixa candidatas para dataset/candidates/, descartando fotos do COCO
    python3 collect_images.py build      # monta images/{train,val,test} a partir de dataset/approved.txt
                                         # (linha "classe/arquivo.jpg test" fixa a imagem no teste)

O COCO foi montado com fotos CC do Flickr, o mesmo acervo do Openverse. Qualquer foto que esteja no COCO
é descartada, porque o YOLO pré-treinado já a viu e isso viciaria a comparação da Entrega 2.

Só usa a biblioteca padrão. A API do Openverse não exige chave no uso anônimo.
"""

import argparse
import csv
import json
import random
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

FASE_DIR = Path(__file__).resolve().parent.parent
DATASET_DIR = FASE_DIR / "dataset"
CANDIDATES_DIR = DATASET_DIR / "candidates"
APPROVED_FILE = DATASET_DIR / "approved.txt"
CACHE_DIR = FASE_DIR / ".cache"
COCO_IDS_FILE = CACHE_DIR / "coco_flickr_ids.txt"

API_URL = "https://api.openverse.org/v1/images/"
USER_AGENT = "fiap-fase6-dataset/1.0"
# Licenças que permitem redistribuir num repo público (com atribuição nas BY/BY-SA)
LICENSES = "cc0,pdm,by,by-sa"
# Termos de busca por classe; variar o termo aumenta a diversidade de cenários
QUERIES = {
    "cow": ["cow", "cattle", "dairy cow"],
    "dog": ["dog", "puppy", "dog park"],
}
CANDIDATES_PER_CLASS = 60  # folga sobre as 40 necessárias para a curadoria descartar o lixo
PER_PAGE = 20  # máximo do uso anônimo
MAX_PAGES = 12  # o uso anônimo limita a busca a 240 resultados (12 x 20)
API_INTERVAL_S = 3.5  # limite anônimo: 20 requisições/min

COCO_ANNOTATIONS_URL = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
# train2017 + val2017 cobrem todas as imagens rotuladas do COCO (o 2014 é a mesma base, dividida de outro jeito)
COCO_MEMBERS = ("annotations/captions_train2017.json", "annotations/captions_val2017.json")

# Divisão exigida pelo enunciado, por classe
SPLITS = (("train", 32), ("val", 4), ("test", 4))
PER_CLASS = sum(n for _, n in SPLITS)
SEED = 42
JPEG_MAGIC = b"\xff\xd8"
# Nome de arquivo do Flickr: <photo_id>_<secret>[_<tamanho>].jpg
FLICKR_FILE_RE = re.compile(r"/(\d+)_[0-9a-f]+(?:_[a-z0-9]+)?\.jpg$")


def open_url(url, timeout=30):
    # Abre a URL com User-Agent próprio; erros HTTP e de rede viram RuntimeError com a URL no contexto
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except OSError as e:  # URLError e HTTPError são subclasses de OSError
        raise RuntimeError(f"falha ao acessar {url}: {e}") from e


def http_get(url, timeout=30):
    with open_url(url, timeout) as resp:
        return resp.read()


def flickr_photo_id(url):
    # Extrai o ID da foto do Flickr a partir da URL da imagem (formato comum ao Openverse e ao COCO)
    match = FLICKR_FILE_RE.search(url)
    if not match:
        raise ValueError(f"URL fora do padrão do Flickr: {url}")
    return int(match.group(1))


def parse_results(raw):
    # Valida a resposta da API e extrai só os campos usados; resposta malformada é erro, não lista vazia
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"resposta da API não é JSON: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError("resposta da API sem a lista 'results'")
    photos = []
    for r in data["results"]:
        try:
            photos.append({
                "flickr_id": flickr_photo_id(r["url"]),
                "openverse_id": r["id"],
                "title": r.get("title") or "",
                "creator": r.get("creator") or "",
                "creator_url": r.get("creator_url") or "",
                "license": r["license"],
                "license_version": r.get("license_version") or "",
                "license_url": r.get("license_url") or "",
                "landing_url": r["foreign_landing_url"],
                "image_url": r["url"],
                "attribution": r.get("attribution") or "",
            })
        except (KeyError, TypeError) as e:
            raise ValueError(f"resultado malformado na resposta da API: {e!r}") from e
    return photos


def fetch_page(query, page):
    # Uma página de resultados; espera entre chamadas para respeitar o limite anônimo
    time.sleep(API_INTERVAL_S)
    params = urllib.parse.urlencode({
        "q": query, "page": page, "page_size": PER_PAGE,
        "license": LICENSES, "source": "flickr", "extension": "jpg",
    })
    return parse_results(http_get(f"{API_URL}?{params}"))


def iter_photos(queries, fetch=fetch_page):
    # Percorre termos e páginas sob demanda, sem repetir foto (deduplica pelo ID do Flickr)
    seen = set()
    for query in queries:
        for page in range(1, MAX_PAGES + 1):
            photos = fetch(query, page)
            if not photos:
                break  # fim dos resultados deste termo
            for photo in photos:
                if photo["flickr_id"] not in seen:
                    seen.add(photo["flickr_id"])
                    yield {**photo, "query": query}


def download_file(url, dest):
    # Baixa de forma atômica (.part + rename) e idempotente (pula se já existe); valida que é JPEG
    if dest.exists():
        return False
    data = http_get(url, timeout=60)
    if not data.startswith(JPEG_MAGIC):
        raise ValueError(f"conteúdo baixado não é JPEG: {url}")
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return True


def collect_class(queries, out_dir, coco_ids, target, fetch=fetch_page, download=download_file):
    # Junta `target` fotos baixadas com sucesso, descartando as do COCO e as que falharem (com aviso)
    kept, stats = [], Counter()
    for photo in iter_photos(queries, fetch):
        if photo["flickr_id"] in coco_ids:
            stats["coco"] += 1
            continue
        dest = out_dir / f"flickr_{photo['flickr_id']}.jpg"
        try:
            download(photo["image_url"], dest)
        except (RuntimeError, ValueError) as e:
            stats["falha"] += 1
            print(f"  descartada {dest.name}: {e}", file=sys.stderr)
            continue
        kept.append({**photo, "file": f"{out_dir.name}/{dest.name}"})
        if len(kept) == target:
            break
    return kept, stats


def load_coco_ids(zip_path):
    # Lê os IDs Flickr de todas as imagens do COCO train2017 + val2017 a partir do zip de anotações
    ids = set()
    with zipfile.ZipFile(zip_path) as zf:
        for member in COCO_MEMBERS:
            with zf.open(member) as f:
                images = json.load(f)["images"]
            for img in images:
                ids.add(flickr_photo_id(img["flickr_url"]))
    return ids


def read_coco_ids(path):
    if not path.is_file():
        sys.exit(f"{path} não existe. Rode primeiro: python3 collect_images.py coco-ids")
    return {int(line) for line in path.read_text(encoding="utf-8").split()}


def cmd_coco_ids(_args):
    if COCO_IDS_FILE.is_file():
        print(f"{COCO_IDS_FILE} já existe; nada a fazer")
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = CACHE_DIR / "annotations_trainval2017.zip"
    if not zip_path.is_file():
        print(f"baixando {COCO_ANNOTATIONS_URL} (~250 MB)...")
        part = zip_path.with_name(zip_path.name + ".part")
        with open_url(COCO_ANNOTATIONS_URL, timeout=120) as resp, open(part, "wb") as f:
            shutil.copyfileobj(resp, f)
        part.replace(zip_path)
    ids = load_coco_ids(zip_path)
    tmp = COCO_IDS_FILE.with_name(COCO_IDS_FILE.name + ".part")
    tmp.write_text("\n".join(str(i) for i in sorted(ids)) + "\n", encoding="utf-8")
    tmp.replace(COCO_IDS_FILE)
    zip_path.unlink()  # o zip só serve para extrair os IDs
    print(f"{len(ids)} IDs Flickr do COCO salvos em {COCO_IDS_FILE}")


def cmd_download(_args):
    coco_ids = read_coco_ids(COCO_IDS_FILE)
    rows = []
    for cls, queries in QUERIES.items():
        out_dir = CANDIDATES_DIR / cls
        out_dir.mkdir(parents=True, exist_ok=True)
        kept, stats = collect_class(queries, out_dir, coco_ids, CANDIDATES_PER_CLASS)
        print(f"{cls}: {len(kept)} candidatas | descartadas por estarem no COCO: {stats['coco']} "
              f"| descartadas por falha: {stats['falha']}")
        if len(kept) < CANDIDATES_PER_CLASS:
            print(f"  AVISO: {cls} ficou abaixo da meta de {CANDIDATES_PER_CLASS}", file=sys.stderr)
        rows.extend({"class": cls, **p} for p in kept)
    # Reescreve o índice inteiro a cada execução (estado absoluto, não incremental)
    with open(CANDIDATES_DIR / "candidates.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"índice salvo em {CANDIDATES_DIR / 'candidates.csv'}")


def read_approved(path, candidates_dir):
    # Lê approved.txt e agrupa por classe. Formato da linha: "classe/arquivo.jpg [test]";
    # o marcador "test" fixa a imagem no conjunto de teste; '#' comenta.
    approved = {cls: [] for cls in QUERIES}
    forced_test = {cls: [] for cls in QUERIES}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        tokens = line.split("#", 1)[0].split()
        if not tokens:
            continue
        rel, flags = tokens[0], tokens[1:]
        if flags not in ([], ["test"]):
            raise ValueError(f"linha {n}: marcador inválido {flags} (o único aceito é 'test')")
        cls = rel.split("/", 1)[0]
        if cls not in approved:
            raise ValueError(f"linha {n}: classe desconhecida '{cls}'")
        if not (candidates_dir / rel).is_file():
            raise FileNotFoundError(f"linha {n}: arquivo não encontrado em candidates/: {rel}")
        approved[cls].append(rel)
        if flags:
            forced_test[cls].append(rel)
    return approved, forced_test


def split_dataset(files, forced_test=(), seed=SEED):
    # Fixa `forced_test` no teste, embaralha o resto com seed fixa (reprodutível)
    # e completa test/train/val nos tamanhos de SPLITS
    if len(set(files)) != len(files):
        raise ValueError("arquivos duplicados na lista de aprovadas")
    if len(files) != PER_CLASS:
        raise ValueError(f"esperadas {PER_CLASS} imagens por classe, recebidas {len(files)}")
    sizes = dict(SPLITS)
    forced = sorted(set(forced_test))
    if not set(forced) <= set(files):
        raise ValueError("imagem fixada no teste fora da lista de aprovadas")
    if len(forced) > sizes["test"]:
        raise ValueError(f"no máximo {sizes['test']} imagens fixadas no teste, recebidas {len(forced)}")
    rest = sorted(set(files) - set(forced))  # ordena antes para não depender da ordem do arquivo
    random.Random(seed).shuffle(rest)
    n_fill = sizes["test"] - len(forced)
    result = {"test": forced + rest[:n_fill]}
    pool, start = rest[n_fill:], 0
    for name, n in SPLITS:
        if name != "test":
            result[name] = pool[start:start + n]
            start += n
    return {name: result[name] for name, _ in SPLITS}


def cmd_build(_args):
    images_dir = DATASET_DIR / "images"
    # Protege rótulos já feitos: não sobrescreve um dataset montado
    if images_dir.exists() and any(images_dir.rglob("*.jpg")):
        sys.exit(f"{images_dir} já contém imagens. Remova a pasta para remontar.")
    with open(CANDIDATES_DIR / "candidates.csv", encoding="utf-8") as f:
        meta = {row["file"]: row for row in csv.DictReader(f)}
    approved, forced_test = read_approved(APPROVED_FILE, CANDIDATES_DIR)
    sources = []
    for cls, files in approved.items():
        index = 1
        for split, chosen in split_dataset(files, forced_test[cls]).items():
            (images_dir / split).mkdir(parents=True, exist_ok=True)
            for src in chosen:
                new_name = f"{cls}_{index:03d}.jpg"
                shutil.copy2(CANDIDATES_DIR / src, images_dir / split / new_name)
                m = meta[src]
                sources.append({
                    "arquivo": new_name, "classe": cls, "split": split,
                    "flickr_id": m["flickr_id"], "url_origem": m["landing_url"],
                    "autor": m["creator"], "licenca": f"{m['license']} {m['license_version']}".strip(),
                    "licenca_url": m["license_url"], "atribuicao": m["attribution"],
                })
                index += 1
    with open(DATASET_DIR / "fontes.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(sources[0].keys()))
        writer.writeheader()
        writer.writerows(sources)
    print(f"{len(sources)} imagens montadas em {images_dir}; créditos em fontes.csv")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("coco-ids", help="extrai os IDs Flickr do COCO").set_defaults(func=cmd_coco_ids)
    sub.add_parser("download", help="baixa candidatas do Openverse").set_defaults(func=cmd_download)
    sub.add_parser("build", help="monta o dataset a partir de approved.txt").set_defaults(func=cmd_build)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

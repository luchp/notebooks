import asyncio
import base64
import datetime
import sys
from pathlib import Path
import ftplib
import nbformat
from traitlets.config import Config
from nbconvert.exporters import HTMLExporter
from nbconvert.preprocessors import TagRemovePreprocessor, ExecutePreprocessor
import requests

asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def load_secrets():
    ret = {}
    with open(Path(__file__).parent / "secrets.txt") as sf:
        for line in sf:
            kv = [x.strip() for x in line.split("#")[0].split("=")]
            if len(kv) == 2 and all(kv):
                ret[kv[0]] = kv[1]
    return ret


def upload_file(secrets, local_path, remote_path):
    with ftplib.FTP(secrets["ftp_server"], secrets["ftp_username"], secrets["ftp_password"]) as ftp:
        with open(local_path, "rb") as fin:
            ftp.storbinary(f"STOR {remote_path}", fin)


def get_notebook_tags(txt):
    tags = {}
    lines = []
    for x in txt.split("\n"):
        if line := x.strip():
            if line[:2] == "#?" and len(line) > 3:
                kv = [x.strip() for x in line[2:].split("#")[0].split("=")]
                if all(kv):
                    tags[kv[0]] = kv[1] if len(kv) > 1 else None
                    continue
        lines.append(line)
    return tags, "\n".join(lines).strip()


def convert_jupyter(nb_path):
    nb_path = Path(nb_path)
    with open(nb_path) as fin:
        read_data = fin.read()
    notebook = nbformat.reads(read_data, as_version=4)
    if not notebook["cells"]:
        raise ValueError("notebook is empty")
    print(f"Executing notebook {nb_path.name} ...")
    try:
        ep = ExecutePreprocessor(timeout=600)
        ep.preprocess(notebook, {"metadata": {"path": str(nb_path.parent)}})
    finally:
        with open(nb_path, mode="w", encoding="utf-8") as fout:
            nbformat.write(notebook, fout)
    #
    # parse cells for metadata,
    # The first cell must contain the metadata for word_press and is always suppressed in the output
    # The remaining cells can have tags to supress output
    #
    print(f"Parse notebook for metadata ...")
    nb_meta, txt = get_notebook_tags(notebook["cells"][0]["source"])
    nb_meta["excerpt"] = txt
    notebook["cells"][0].setdefault("metadata", {})["tags"] = ["remove_cell"]
    for c in notebook["cells"][1:]:
        c_meta, txt = get_notebook_tags(c["source"])
        c["source"] = txt
        cell_tags = set(c.setdefault("tags", [])) | set(c_meta.keys())
        if not txt:
            cell_tags.add("remove_cell")
        c.setdefault("metadata", {})["tags"] = list(cell_tags)

    if not nb_meta.get("title"):
        raise ValueError("First notebook cell must contain 'title'' metadata")
    if not nb_meta.get("excerpt"):
        raise ValueError("First notebook cell must contain 'categories' metadata")
    nb_meta["categories"] = nb_meta["categories"].split(";")
    if not nb_meta.get("title"):
        raise ValueError("First notebook cell must contain 'tags' metadata")
    nb_meta["tags"] = nb_meta["tags"].split(";")
    if not nb_meta.get("excerpt"):
        raise ValueError("First notebook cell must contain excerpt text")
    #
    # Instruct exporter to strip output based on tags
    print(f"Exporting notebook ...")
    c = Config()
    c.TagRemovePreprocessor.remove_cell_tags = ("remove_cell",)
    c.TagRemovePreprocessor.remove_all_outputs_tags = ("remove_output",)
    c.TagRemovePreprocessor.remove_input_tags = ("remove_input",)
    c.TagRemovePreprocessor.enabled = True

    # Configure and run out exporter
    c.HTMLExporter.preprocessors = ["nbconvert.preprocessors.TagRemovePreprocessor"]
    exporter = HTMLExporter(config=c)
    exporter.register_preprocessor(TagRemovePreprocessor(config=c), True)
    (body, resources) = exporter.from_notebook_node(notebook)
    # save result
    out_path = nb_path.with_suffix(".html")
    with open(out_path, "wb") as fout:
        fout.write(body.encode())
    return out_path, nb_meta

def wp_auth(secrets, endpoint):
    url = secrets["wp_apiurl"] + endpoint
    user = secrets["wp_username"]
    password = secrets["wp_password"]
    credentials = user + ":" + password
    token = base64.b64encode(credentials.encode())
    header = {"Authorization": "Basic " + token.decode("utf-8")}
    return url, header

def check_categories(secrets, cat_list=None):
    print("Checking categories ...")
    if not cat_list:
        raise ValueError("No categories found")
    url, header = wp_auth(secrets, "categories")
    response = requests.get(url, headers=header)
    response.raise_for_status()
    data = response.json()
    cat_dict = {d["name"].casefold(): d["id"] for d in data }
    cats = []
    for c in cat_list:
        if cid := cat_dict.get(c):
            cats.append(cid)
        else:
            raise ValueError(f"Unknown category {c}")
    return cats

def create_post(secrets, remote_path, nb_meta):
    print("Posting notebook ...")
    url, header = wp_auth(secrets, "posts")
    post = {
        "title": nb_meta["title"],
        "status": "publish",
        "content": f'[iframe src="{remote_path}" width="100%"]',
        "categories": nb_meta["cat_ids"],
        "excerpt": nb_meta["excerpt"],
        "date": nb_meta.get("date", datetime.datetime.now().isoformat()),
    }

    response = requests.post(url, headers=header, json=post)
    response.raise_for_status()

def main(nb_path):
    html_path, nb_meta = convert_jupyter(nb_path)
    secrets = load_secrets()
    nb_meta["cat_ids"] = check_categories(secrets, nb_meta["categories"])
    remote_path = secrets["ftp_notebook_dir"] + html_path.name
    upload_file(secrets, html_path, remote_path)
    ret = input("Create post? ")
    if ret.casefold() in ["y", "yes"]:
        remote_path = secrets["wp_notebook_dir"] + html_path.name
        create_post(secrets, remote_path, nb_meta)
    print("Done!", nb_meta)

#main(Path(__file__).parent / "test.ipynb")
main(sys.argv[1])

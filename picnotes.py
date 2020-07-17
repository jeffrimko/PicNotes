##==============================================================#
## SECTION: Imports                                             #
##==============================================================#

from datetime import datetime
from tempfile import gettempdir
import os.path as op
import os
import sys

from auxly.stringy import randomize, between
import auxly
import qprompt
import enchant
import click

##==============================================================#
## SECTION: Function Definitions                                #
##==============================================================#

def process_pic_basic(pic, tmp_png):
    """Use this for basic blue text extraction. Results in some
    extra stuff depending on the pic."""
    cmd = f"magick convert {pic} -resize 80% -fill white -fuzz 30% +opaque blue {tmp_png}"
    auxly.shell.silent(cmd)

def process_pic_yellow_mask(pic, tmp_png):
    """Use this when all the notes use blue text on the rgb(255,255,185)
    yellowish background. Results in virtually no extra stuff."""
    # Creates black mask areas.
    cmd = f"magick convert {pic} -fill white +opaque rgb(255,255,185) -blur 10 -negate -threshold 0 -negate {tmp_png}"
    auxly.shell.call(cmd)

    # Shows only notes.
    # cmd = f"magick convert {tmp_png} {pic} -compose minus -composite {tmp_png}"  # NOTE: This sometimes resulted in the blue text incorrectly turning to black.
    cmd = f"magick convert {pic} {tmp_png} -negate -channel RBG -compose minus -composite {tmp_png}"
    auxly.shell.call(cmd)

    # Finds only blue.
    cmd = f"magick convert {tmp_png} -fill white -fuzz 25% +opaque blue {tmp_png}"
    auxly.shell.call(cmd)

def process_notes_basic(text):
    """Use this when there is little risk of extra stuff in the processed pic."""
    lines = text.strip().splitlines()
    notes = " ".join(lines)
    return notes

def process_notes_dict(text):
    """Use this when there might be extra stuff in the processed pic,
    attempts to eliminate gibberish."""
    good_lines = []
    lines = text.strip().splitlines()
    d = enchant.Dict("en_US")
    for line in lines:
        if not line: continue
        for word in line.split():
            if d.check(word):
                good_lines.append(line)
                break
    notes = " ".join(good_lines)
    return notes

def get_notes(pic):
    tmp = op.join(gettempdir(), randomize())
    tmp_png = tmp + ".png"
    tmp_txt = tmp + ".txt"
    process_pic_yellow_mask(pic, tmp_png)

    # NOTE: Using tmp as output because ".txt" extension is added automatically
    # by Tesseract.
    auxly.shell.silent(f"tesseract {tmp_png} {tmp}")

    text = auxly.filesys.File(tmp_txt).read()
    if text:
        notes = process_notes_basic(text)
        return notes

def create_picnotes(dirpath, confirm=True, shrink=False):
    """Attempts to extract notes from all pics found under the given directory
    and write them to a file."""
    dirpath = op.abspath(dirpath)
    titlepath = os.sep.join(dirpath.split(os.sep)[-2:])
    pics = list(auxly.filesys.walkfiles(dirpath, ".(png|jpg)", recurse=True))
    if not pics:
        qprompt.warn("No pics found under directory!")
        return
    pics = sort_pics(pics)
    qprompt.alert(f"Found {len(pics)} pics found under directory.")
    doc = auxly.filesys.File(dirpath, "pic_notes.adoc")
    existing_notes = {}
    if doc.exists():
        existing_notes = parse_picnotes(doc)
        if confirm:
            if not qprompt.ask_yesno(f"The `pic_notes.adoc` file already exists with {len(existing_notes)} pic notes found, overwrite it?"):
                return
    doc.empty()
    qprompt.alert(f"Initialized file `{doc.path}`")
    doc.appendline(f"= PIC NOTES: `{titlepath}`")
    doc.appendline(":date: " + datetime.now().strftime("%d %B %Y %I:%M%p"))
    doc.appendline("")
    doc.appendline("NOTE: Entries sorted by base filename.")
    doc.appendline("")
    count = {'reused': 0, 'scanned': 0}
    for idx,picpath in enumerate(pics, 1):
        relpath = op.relpath(picpath, dirpath)
        msg = f"({idx} of {len(pics)})"
        if relpath in existing_notes.keys() and auxly.filesys.checksum(picpath) == existing_notes[relpath]['md5']:
            qprompt.alert(f"{msg} Reusing `{picpath}`.")
            notes = existing_notes[relpath]['note']
            if shrink:
                attempt_shrink(picpath, notes)
            line = existing_notes[relpath]['line']
            count['reused'] += 1
        else:
            notes = qprompt.status(f"{msg} Scanning `{picpath}`...", get_notes, [picpath]) or "NA"
            if shrink:
                attempt_shrink(picpath, notes)
            line = f"  - link:{relpath}[] [[md5_{auxly.filesys.checksum(picpath)}]] - {notes}"
            count['scanned'] += 1
        doc.appendline(line)
    return count

def attempt_shrink(picpath, old_notes):
    old_size = auxly.filesys.File(picpath).size()
    tmppath = op.join(gettempdir(), "__temp-shrink.png")
    cmd = f"pngquant --quality=60-75 --output {tmppath} {picpath}"
    auxly.shell.call(cmd)
    new_size = auxly.filesys.File(tmppath).size()
    if new_size < old_size:
        new_notes = get_notes(tmppath)
        if new_notes == old_notes:
            if auxly.filesys.move(tmppath, picpath):
                qprompt.alert(f"Saved {old_size - new_size} bytes shrinking `{picpath}`.")
                return
    qprompt.alert(f"Could not shrink `{picpath}`.")
    auxly.filesys.delete(tmppath)

def parse_picnotes(doc):
    existing_notes = {}
    for line in doc.read().splitlines():
        if line.lstrip().startswith("- link:"):
            try:
                entry = {}
                entry['file'] = between(line, "link:", "[]")
                entry['md5'] = between(line, "[[md5_", "]]")
                entry['note'] = line.split("]] - ")[1]
                entry['line'] = line
                existing_notes[entry['file']] = entry
            except:
                pass
    return existing_notes

def sort_pics(pics):
    sorted_pics = sorted(pics, key=lambda p: op.basename(p))
    return sorted_pics

@click.group()
def cli(**kwargs):
    return True

@cli.command()
@click.option("--scandir", default=".", show_default=True, help="Directory to scan and create notes in.")
@click.option("--picdirname", default="pics", show_default=True, help="Name of pic directories.")
@click.option("--overwrite", is_flag=True, help="Always overwrite existing notes.")
@click.option("--shrink", is_flag=True, help="Attempt to shrink pics.")
def scan(scandir, picdirname, overwrite, shrink):
    """Scan scandir and all subdirectories for pics. Note text will be
    extracted and a notes file will be created under scandir."""
    dirpath = auxly.filesys.Path(scandir)
    if not dirpath.isdir():
        qprompt.fatal("Given path must be existing directory!")
    if picdirname != dirpath.name:
        if not qprompt.ask_yesno("Directory not named `pics`, continue?"):
            sys.exit()
    create_picnotes(dirpath, confirm=not overwrite, shrink=shrink)

@cli.command()
@click.option("--startdir", default=".", show_default=True, help="The walk start directory.")
@click.option("--picdirname", default="pics", show_default=True, help="Name of pic directories.")
def walk(startdir, picdirname):
    """Walk all directories under startdir and scan when directory name matches
    picdirname. Existing notes are overwritten."""
    if not op.isdir(startdir):
        qprompt.fatal("Given path must be existing directory!")

    total_count = {'reused': 0, 'scanned': 0}
    for d in auxly.filesys.walkdirs(startdir, "pics"):
        if op.basename(d) != picdirname:
            continue
        qprompt.hrule()
        qprompt.alert(f"Walking through `{d}`...")
        dirpath = auxly.filesys.Path(d)
        new_count = create_picnotes(dirpath, False)
        total_count['reused'] += new_count['reused']
        total_count['scanned'] += new_count['scanned']
    qprompt.alert(f"Walk complete, scanned={total_count['scanned']} reused={total_count['reused']}")
    sys.exit()

##==============================================================#
## SECTION: Main Body                                           #
##==============================================================#

if __name__ == '__main__':
    cli(obj={})

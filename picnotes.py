##==============================================================#
## SECTION: Imports                                             #
##==============================================================#

from datetime import datetime
from tempfile import gettempdir
import os
import os.path as op
import sys

from auxly.stringy import randomize, between
import auxly
import click
import qprompt

##==============================================================#
## SECTION: Function Definitions                                #
##==============================================================#

def process_pic_yellow_mask(picpath, tmppath):
    """Use this when all the notes use blue text on the rgb(255,255,185)
    yellowish background. Results in virtually no extra stuff."""
    # Creates black mask areas.
    cmd = f"magick convert {picpath} -fill white +opaque rgb(255,255,185) -blur 10 -negate -threshold 0 -negate {tmppath}"
    auxly.shell.silent(cmd)

    # Shows only notes.
    # cmd = f"magick convert {tmppath} {picpath} -compose minus -composite {tmppath}"  # NOTE: This sometimes resulted in the blue text incorrectly turning to black.
    cmd = f"magick convert {picpath} {tmppath} -negate -channel RBG -compose minus -composite {tmppath}"
    auxly.shell.silent(cmd)

    # Finds only blue.
    cmd = f"magick convert {tmppath} -fill white -fuzz 25% +opaque blue {tmppath}"
    auxly.shell.silent(cmd)

def process_notes_basic(text):
    """Use this when there is little risk of extra stuff in the processed pic."""
    lines = text.strip().splitlines()
    notes = " ".join(lines)
    return notes

def get_notes(picpath):
    """Attempts to return note text from the given pic."""
    tmp = op.join(gettempdir(), randomize())
    tmp_png = tmp + ".png"
    process_pic_yellow_mask(picpath, tmp_png)

    # NOTE: Using tmp as output because ".txt" extension is added automatically
    # by Tesseract.
    auxly.shell.silent(f"tesseract {tmp_png} {tmp}")

    tmp_txt = tmp + ".txt"
    text = auxly.filesys.File(tmp_txt).read()

    auxly.filesys.delete(tmp_png)
    auxly.filesys.delete(tmp_txt)
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
    doc.appendline(":toc:")
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
            line = format_adoc_line(relpath, picpath, notes)
            count['reused'] += 1
        else:
            notes = qprompt.status(f"{msg} Scanning `{picpath}`...", get_notes, [picpath]) or "NA"
            if shrink:
                attempt_shrink(picpath, notes)
            line = format_adoc_line(relpath, picpath, notes)
            count['scanned'] += 1
        doc.appendline(line)
    return count

def format_adoc_line(relpath, picpath, notes):
    line = ""
    line += f"== {relpath}\n"
    line += f"  - link:{relpath}[window='_blank']  [[md5_{auxly.filesys.checksum(picpath)}]] - {notes}\n"
    line += f"+\n"
    line += f"link:{relpath}[ image:{relpath}[width=35%] , window='_blank']\n"
    return line

def attempt_shrink(picpath, old_notes):
    old_size = auxly.filesys.File(picpath).size()
    tmppath = op.join(gettempdir(), "__temp-shrink.png")
    cmd = f"pngquant --quality=40-60 --output {tmppath} {picpath}"
    auxly.shell.silent(cmd)
    new_size = auxly.filesys.File(tmppath).size()
    if new_size and old_size:
        if new_size < old_size:
            new_notes = get_notes(tmppath) or "NA"
            if new_notes == old_notes:
                if auxly.filesys.move(tmppath, picpath):
                    qprompt.alert(f"Saved {old_size - new_size} bytes shrinking `{picpath}`.")
                    return True
    qprompt.alert(f"Could not shrink `{picpath}`.")
    auxly.filesys.delete(tmppath)
    return False

def parse_picnotes(doc):
    existing_notes = {}
    for line in doc.read().splitlines():
        if line.lstrip().startswith("- link:"):
            try:
                entry = {}
                entry['file'] = between(line, " - link:", "[")
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
@click.option("--shrink", is_flag=True, help="Attempt to shrink size of pics.")
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
        if new_count:
            total_count['reused'] += new_count['reused']
            total_count['scanned'] += new_count['scanned']
    qprompt.alert(f"Walk complete, scanned={total_count['scanned']} reused={total_count['reused']}")
    sys.exit()

##==============================================================#
## SECTION: Main Body                                           #
##==============================================================#

if __name__ == '__main__':
    cli(obj={})

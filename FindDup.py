""" Requires Python 2.7 """

from Tkinter import *
import time
#from Tkinter import filedialog  ## python3.6
import tkFileDialog
import os
import itertools
#from os import walk
#import win32api
#import pathlib
#from pathlib import Path
#from scikits.audiolab import
#import acoustid
from distutils.dir_util import mkpath
from shutil import copyfile
#import audiodiff
import locale
#import sqlite3
#import subprocess
from dejavu import Dejavu
from dejavu.recognize import FileRecognizer
from Scrollable import Scrollable


songs_path = None
img_dir = None
dups_dir = None

def selectDir():
    global songs_path, img_dir, dups_dir
    Tk().withdraw()
    songs_path = tkFileDialog.askdirectory(initialdir = "~/Desktop/.",title = "Select Songs Location")
    #songs_dir = os.path.dirname(songs_path)
    img_dir = songs_path + "/TempForDups" + "/"
    mkpath(img_dir)
    dups_dir = songs_path + "/Duplicates" + "/"
    mkpath(dups_dir)
    #pathlib.Path(songs_path + "/KaraSpectrum").mkdir(parents=True, exist_ok=True)

def findDups():

    files = [f for f in os.listdir(songs_path) if re.match(r'.*\.(?:wav|mp3|flac|m4a)', f)]

    # copy all files to a temp dir, with their index as their name, since there's no support for unicode (hebrew) file names
    for idx, val in enumerate(files):
        ext = os.path.splitext(val)[1]
        #print(songs_path+'/'+val + "    |   "+ img_dir + str(idx) + ext)
        copyfile(songs_path+'/'+val, img_dir +  str(idx) + ext)

    # Create dejavu object
    config = {
        "fingerprint_limit" : 150, #seconds. some files may have differfent trailing - no need to account for this
        "database_type": "sqlite",
        "database": {
            "db": img_dir+'kara_find_duplicates',
        }
    }
    djv = Dejavu(config)

    print("Building database of songs...")
    # #fingerprint all files
    starttime = time.time()
    djv.fingerprint_directory(img_dir.replace('\\', '/'), [".mp3",".wav",".m4a",".mp4",".flac"], 0)
    print("Done fingerprinting ("+str(int(time.time()-starttime))+" seconds)")

    #print(djv.db.get_num_fingerprints())
    #for line in djv.db.cursor().conn.iterdump():
    #    print(line)

    def move_duplicate_files():
        btn['state'] = DISABLED
        btn['text']="Moving..."
        for checkboxvar in checkboxesvars:
            if checkboxvar.get():
                try:
                    print("Moving "+songs_path +"/"+checkboxvar.get())
                    os.rename(songs_path +"/"+checkboxvar.get(), dups_dir+checkboxvar.get())
                except OSError:
                    print("Error - most probably file already moved.")
                    pass
                for checkbox in checkboxes:
                    if checkbox["onvalue"]==checkboxvar.get():
                        checkboxes.remove(checkbox)
                        checkbox.deselect()
                        checkbox.destroy()
#               subprocess.call(['start', (songs_path +"/"+checkbox.get()).encode('ascii', 'ignore')])
        btn['state'] = 'normal'
        btn['text']="Move selected to ./Duplicates"


    # this function is called whenever a checkbox is clicked, and it changes all the checkboxes of the same song (a song can appear more than once) to the same selected/unselected state
    def change_identical_song(val,name):
        for checkbox in checkboxes:
            if checkbox["onvalue"]==name:
                if val.get():
                    checkbox.select()
                else:
                    checkbox.deselect()


    master = Tk()
    master.title("Duplicates Found")
    btn = Button(master, text="Move selected to ./Duplicates", command=move_duplicate_files)
    btn.pack()
    l1 = Label(master, text="Songs in green are suspected as duplicates", bg="#B3FCC0", anchor='w')
    l1.pack(fill=BOTH)
    root = Scrollable(master)
    checkboxes = []
    checkboxesvars = []

    for idx, val in enumerate(files):
        #if idx>4:
        #    continue
        extc = os.path.splitext(val)[1]
        print("==============================")
        print("Looking for duplicates for: "+val+" ("+str(idx)+")")
        songs = djv.recognize(FileRecognizer, (img_dir+str(idx)+extc).replace('\\', '/'))
        songs1, songs2 = itertools.tee(songs)

        l0 = Label(root, text="     ")
        l0.pack()
        l1 = Label(root, text="The following songs are duplicates:", bg="blue", fg="white", anchor='w')
        l1.pack(fill=BOTH)

        #l2 = Label(root, text="Duplicates for "+val, bg="blue", fg="white", justify=LEFT)
        checkboxesvars.append(StringVar(root))
        #l2 = Label(root, text="Duplicates for " + val, bg="blue", fg="white", justify=LEFT)
        l2 = Checkbutton(root, text=val, variable=checkboxesvars[-1], anchor='w', onvalue=val, offvalue="",
                         command=lambda var=checkboxesvars[-1], name=val: change_identical_song(var, name))
        checkboxes.append(l2)
        l2.deselect()
        l2.pack(fill=BOTH)

        found_identical = False

        for song in songs1:
            #print( song)
            if int(song["song_name"])==idx:
                continue
            if (song["confidence"])==1:
                print(files[int(song["song_name"])]+" (identical)")
                checkboxesvars.append(StringVar(root))
                #for i in range(50):
                checkboxes.append(Checkbutton(root, text=files[int(song["song_name"])], variable=checkboxesvars[-1],
                              anchor='w', onvalue=files[int(song["song_name"])], offvalue="",
                              command=lambda var=checkboxesvars[-1], name=files[int(song["song_name"])] : change_identical_song(var, name)))
                checkboxes[-1].deselect()
                checkboxes[-1].pack(fill=BOTH)
                found_identical = True

        #l3 = Label(root, text="    suspected duplicates:    ", bg="green", fg="white", justify=LEFT)
        #l3.pack()
        found_suspected = False
        for song in songs2:
            #print( song)
            if int(song["song_name"])==idx:
                continue
            if (song["confidence"])<1:
                print(files[int(song["song_name"])]+" (suspected)")
                checkboxesvars.append(StringVar(root))
                checkboxes.append(Checkbutton(root, text=files[int(song["song_name"])]+ " (maybe)", variable=checkboxesvars[-1],
                            onvalue=files[int(song["song_name"])], offvalue="", bg="#B3FCC0", anchor='w',
                            command=lambda var=checkboxesvars[-1], name=files[int(song["song_name"])]: change_identical_song(var,name)))
                checkboxes[-1].deselect()
                checkboxes[-1].pack(fill=BOTH)
                found_suspected = True

        if not found_suspected:
            #l3.pack_forget()
            if not found_identical:
                l1.pack_forget()
                l0.pack_forget()
                l2.pack_forget()


    print("Analysis done")

    # remove temporary files. TODO remove the whole directory, including the database
    for file in os.listdir(img_dir):
        if file.endswith(".mp3") or file.endswith(".wav") or file.endswith(".m4a") or file.endswith(".mp4") or file.endswith(".flac"):
            os.remove(os.path.join(img_dir, file))

    def win_quit():
        master.destroy()

    master.protocol("WM_DELETE_WINDOW", win_quit)
    root.update()
    btn.lift()  # make sure it's always visible, even when scrollbar scrolls items on top of it
    master.update()
    master.mainloop()


'''
    i = 0
    while files:
        print ("---------------------------------------------")
        master = files.pop(0)
        ext = os.path.splitext(master)[1]
        print(master)

        for idx, comp in enumerate(files):
            extc = os.path.splitext(comp)[1]
            print((img_dir +  str(i) + ext).encode(locale.getpreferredencoding()), (img_dir  + str(i+idx+1) + extc).encode(locale.getpreferredencoding()))
            if audiodiff.audio_equal((img_dir +  str(i) + ext).encode(locale.getpreferredencoding()), (img_dir  + str(i+idx+1) + extc).encode(locale.getpreferredencoding())):
                print(master + "    and   " + comp + "   are the same".encode('ascii','replace'))

        i += 1
'''


    #for (dirpath, dirnames, filenames) in walk(songs_path):
    #    for file in filenames:
    #        print(file)

    #audiodiff.audio_equal('airplane.flac', 'airplane.m4a')

'''
    for x in Path(songs_path).iterdir():
        if x.is_file() and \
                (x.name.endswith(".mp3") or x.name.endswith(".wav")):
            print(x, " ", x.name, " ", x.suffix)
'''

def main():
    selectDir()
    if not songs_path:
        print("Nothing selected")
    else:
        print("Selected path: "+ songs_path)
        findDups()

main()
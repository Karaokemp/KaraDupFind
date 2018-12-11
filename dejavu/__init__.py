from dejavu.database import get_database, Database
import dejavu.decoder as decoder
import fingerprint
import multiprocessing
import os
import traceback
import sys
import itertools
from shutil import copyfile


class Dejavu(object):

    SONG_ID = "song_id"
    SONG_NAME = 'song_name'
    CONFIDENCE = 'confidence'
    MATCH_TIME = 'match_time'
    OFFSET = 'offset'
    OFFSET_SECS = 'offset_seconds'

    def __init__(self, config):
        super(Dejavu, self).__init__()

        self.config = config

        # initialize db
        db_cls = get_database(config.get("database_type", None))

        self.db = db_cls(**config.get("database", {}))
        self.db.setup()

        # if we should limit seconds fingerprinted,
        # None|-1 means use entire track
        self.limit = self.config.get("fingerprint_limit", None)
        if self.limit == -1:  # for JSON compatibility
            self.limit = None
        self.get_fingerprinted_songs()

    def get_fingerprinted_songs(self):
        # get songs previously indexed
        self.songs = self.db.get_songs()
        self.songhashes_set = set()  # to know which ones we've computed before
        for song in self.songs:
            song_hash = song[Database.FIELD_FILE_SHA1]
            self.songhashes_set.add(song_hash)

    def fingerprint_directory(self, path, extensions, nprocesses=None):
        # Try to use the maximum amount of processes if not given.
        try:
            nprocesses = nprocesses if nprocesses is not None else multiprocessing.cpu_count()
        except NotImplementedError:
            nprocesses = 1
        else:
            nprocesses = 1 if nprocesses < 0 else nprocesses

        if nprocesses:
            pool = multiprocessing.Pool(nprocesses)

        filenames_to_fingerprint = []
        for filename, _ in decoder.find_files(path, extensions):

            # don't refingerprint already fingerprinted files
            if decoder.unique_hash(filename) in self.songhashes_set:
                print "%s already fingerprinted, continuing..." % filename
                continue

            filenames_to_fingerprint.append(filename)

        # Prepare _fingerprint_worker input
        worker_input = zip(filenames_to_fingerprint,
                           [self.limit] * len(filenames_to_fingerprint))

        # Send off our tasks
        if nprocesses:
            iterator = pool.imap_unordered(_fingerprint_worker,
                                           worker_input)
        else:
            iterator = itertools.imap(_fingerprint_worker,
                                           worker_input)


        # Loop till we have all of them
        while True:
            try:
                song_name, hashes, file_hash = iterator.next()
            except multiprocessing.TimeoutError:
                continue
            except StopIteration:
                break
            except:
                print("Failed fingerprinting")
                # Print traceback because we can't reraise it here
                traceback.print_exc(file=sys.stdout)
            else:
                sid = self.db.insert_song(song_name, file_hash)

                self.db.insert_hashes(sid, hashes)
                self.db.set_song_fingerprinted(sid)
                self.get_fingerprinted_songs()

        if nprocesses:
            pool.close()
            pool.join()

    def fingerprint_file(self, filepath, song_name=None):
        songname = decoder.path_to_songname(filepath)
        song_hash = decoder.unique_hash(filepath)
        song_name = song_name or songname
        # don't refingerprint already fingerprinted files
        if song_hash in self.songhashes_set:
            print "%s already fingerprinted, continuing..." % song_name
        else:
            song_name, hashes, file_hash = _fingerprint_worker(
                filepath,
                self.limit,
                song_name=song_name
            )
            sid = self.db.insert_song(song_name, file_hash)

            self.db.insert_hashes(sid, hashes)
            self.db.set_song_fingerprinted(sid)
            self.get_fingerprinted_songs()

    def find_matches(self, samples, Fs=fingerprint.DEFAULT_FS):
        hashes = fingerprint.fingerprint(samples, Fs=Fs)
        return self.db.return_matches(hashes)

    def align_matches(self, matches):
        """
            Finds hash matches that align in time with other matches and finds
            consensus about which hashes are "true" signal from the audio.

            Returns a dictionary with match information.
        """

        max_count_per_sid = {}

        # align by diffs
        diff_counter = {}
        largest = 0
        largest_count = 0
        song_id = -1
        for tup in matches:
            sid, diff = tup
            if diff not in diff_counter:
                diff_counter[diff] = {}
            if sid not in diff_counter[diff]:
                diff_counter[diff][sid] = 0
            diff_counter[diff][sid] += 1

            last_sid = 0
            if diff_counter[diff][sid] > largest_count:
                largest = diff
                largest_count = diff_counter[diff][sid]
                song_id = sid

            if (sid not in max_count_per_sid) or (max_count_per_sid[sid]<diff_counter[diff][sid]):
                max_count_per_sid[sid] = diff_counter[diff][sid]

        max_count_per_sid_copy = max_count_per_sid.copy()
        for sid in max_count_per_sid_copy:
            if (max_count_per_sid[sid]<(largest_count/10)): #TODO why 10?
                del max_count_per_sid[sid]

        for sid in max_count_per_sid:
            # extract idenfication
            song = self.db.get_song_by_id(sid)
            if song:
                # TODO: Clarify what `get_song_by_id` should return.
                songname = song.get(Dejavu.SONG_NAME, None)
            else:
                continue

            # return match info
            nseconds = round(float(largest) / fingerprint.DEFAULT_FS *
                             fingerprint.DEFAULT_WINDOW_SIZE *
                             fingerprint.DEFAULT_OVERLAP_RATIO, 5)

            confidence = float(max_count_per_sid[sid])/float(largest_count) # 1=sure, <1=maybe the same song

            if confidence==1.0:
                pass #todo remove this from db, so that we: 1. don't show all songs twice; 2. don't do n^2 comparisons

            song = {
                Dejavu.SONG_ID : sid,
                Dejavu.SONG_NAME : songname,
                Dejavu.CONFIDENCE : confidence,
                Dejavu.OFFSET : int(largest),
                Dejavu.OFFSET_SECS : nseconds,
                Database.FIELD_FILE_SHA1 : song.get(Database.FIELD_FILE_SHA1, None),}
            yield song

    def recognize(self, recognizer, *options, **kwoptions):
        r = recognizer(self)
        return r.recognize(*options, **kwoptions)


def _fingerprint_worker(filename, limit=None, song_name=None, temp_path="DupsDatabase"):
    # Pool.imap sends arguments as tuples so we have to unpack
    # them ourself.
    try:
        filename, limit = filename
    except ValueError:
        pass

    songname, extension = os.path.splitext(os.path.basename(filename))
    song_name = song_name or songname
    temp_filename = filename

    if temp_path: #copy to a temp file because ffmpeg doesn't support unicode (e.g. hebrew) file names
        basename = os.path.basename(filename)
        basepath = os.path.dirname(filename)
        targetpath = basepath + "/" + temp_path + "/"
        ext = os.path.splitext(filename)[1]
        newname = targetpath + "temp" + ext
        print("Copying " + filename +"  -->  "+newname)
        copyfile(filename, newname)
        temp_filename = newname

    channels, Fs, file_hash = decoder.read(temp_filename, limit)
    result = set()
    channel_amount = len(channels)

    for channeln, channel in enumerate(channels):
        # TODO: Remove prints or change them into optional logging.
        print("Fingerprinting channel %d/%d for %s" % (channeln + 1,
                                                       channel_amount,
                                                       filename))
        hashes = fingerprint.fingerprint(channel, Fs=Fs)
        print("Finished channel %d/%d for %s" % (channeln + 1, channel_amount,
                                                 filename))
        result |= set(hashes)

    return song_name, result, file_hash


def chunkify(lst, n):
    """
    Splits a list into roughly n equal parts.
    http://stackoverflow.com/questions/2130016/splitting-a-list-of-arbitrary-size-into-only-roughly-n-equal-parts
    """
    return [lst[i::n] for i in xrange(n)]

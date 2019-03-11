# coding=utf-8

"""
DCRM - Darwin Cydia Repository Manager
Copyright (C) 2017  WU Zheng <i.82@me.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

from __future__ import unicode_literals

import gzip
import os
import shutil
import tarfile
import tempfile
import time

from debian.copyright import parse_multiline, format_multiline
from debian.deb822 import Deb822
from django.conf import settings
from django.utils.translation import ugettext as _


class DebianPackage(object):
    """
    This class manages every thing related to .deb files on file system and
    their control part in Debian RFC822 format.
    
    Some adjustment to package: https://packages.debian.org/sid/python-debian
    Which is really helpful because in python-debian, Debfile is read-only.
    """
    
    def __init__(self, path):
        tempfile.tempdir = settings.TEMP_ROOT
        self.path = path
        self.version = ""
        self.control = {}
        self.size = os.path.getsize(path)
        self.offset_control = 0
        self.length_control = 0
        self.offset_data = 0
        self.length_data = 0
        self.load()
    
    def load(self):
        """
        Load offsets and control dict
        """
        has_flag = False
        has_control = False
        has_data = False
        # https://en.wikipedia.org/wiki/Deb_(file_format)
        fd = open(self.path, 'rb')
        fd.seek(0)
        magic = fd.read(8)
        if magic != b"!<arch>\n":
            raise IOError(_('Not a Debian Package'))
        while True:
            is_flag = False
            is_control = False
            is_data = False
            identifier_d = fd.read(16).rstrip()
            if len(identifier_d) == 0:
                break
            elif identifier_d[:13] == b'debian-binary':
                has_flag = True
                is_flag = True
            elif identifier_d[:7] == b'control':
                has_control = True
                is_control = True
            elif identifier_d[:4] == b'data':
                has_data = True
                is_data = True
            # timestamp_d =
            fd.read(12).rstrip()
            # ownerID_d =
            fd.read(6).rstrip()
            # groupID_d =
            fd.read(6).rstrip()
            # mode_d =
            fd.read(8).rstrip()
            size_d = fd.read(10).rstrip()
            endc = fd.read(2)
            if endc != b'`\n':
                raise IOError(_('Malformed Debian Package'))
            size = int(size_d)
            if is_flag:
                if size != 4:
                    raise IOError(_('Malformed Debian Package'))
                else:
                    self.version = fd.read(4).rstrip().decode()
            elif is_control:
                self.offset_control = fd.tell() - 60
                self.length_control = size
                control_data = fd.read(size)
                temp = tempfile.NamedTemporaryFile(delete=False)
                temp.write(control_data)
                temp.close()
                control_tar = tarfile.open(temp.name)
                control_names = control_tar.getnames()
                control_name = None
                if "./control" in control_names:
                    control_name = "./control"
                elif "control" in control_names:
                    control_name = "control"
                if control_name is None:
                    raise IOError('No Control Info')
                control_obj = control_tar.extractfile(control_name)
                
                # Using Deb822 to parse control
                # Decoded automatically
                control_dict = {}
                rfc822 = Deb822(control_obj)
                for (k, v) in rfc822.items():
                    control_dict[k] = v
                if "Description" in control_dict.keys():
                    control_dict["Description"] = parse_multiline(control_dict.get("Description", ""))
                self.control = control_dict
                
                control_obj.close()
                control_tar.close()
                os.remove(temp.name)
            else:
                if is_data:
                    self.offset_data = fd.tell() - 60
                    self.length_data = size
                fd.seek(fd.tell() + size)
            if size % 2 == 1:
                fd.read(1)  # Even Padding
        if not (has_flag and has_control and has_data):
            raise IOError(_('Malformed Debian Package'))
    
    @staticmethod
    def value_for_field(field):
        """
        Parse info string like: i_82 <i.82@me.com>
        return its former part
        :param field: Info string
        :type field: str
        :return: Former Value
        :rtype: str
        """
        if field is None:
            return None
        lt_index = field.find('<')
        if lt_index > 0:
            gt_index = field.find('>', lt_index)
            if gt_index > 0:
                return field[:lt_index].strip()
            else:
                return field
        else:
            return field
    
    @staticmethod
    def detail_for_field(field):
        """
        Parse info string like: i_82 <i.82@me.com>
        return its latter part
        :param field: Info string
        :type field: str
        :return: Latter Value
        :rtype: str
        """
        if field is None:
            return None
        lt_index = field.find('<')
        if lt_index > 0:
            gt_index = field.find('>', lt_index)
            if gt_index > 0:
                return field[lt_index + 1:gt_index].strip()
            else:
                return ''
        else:
            return ''
    
    @staticmethod
    def get_control_content(control_dict, fd=None):
        """
        :param fd: If fd is None, returns a unicode object.  Otherwise, fd is assumed to
        be a file-like object, and this method will write the data to it
        instead of returning a unicode object.
        :type control_dict: Dictionary
        :rtype: str
        :return: Control in RFC822 Format
        """
        # Using Deb822 to format control
        if "Description" in control_dict.keys():
            control_dict["Description"] = format_multiline(control_dict["Description"])
        rfc822 = Deb822(control_dict)
        if fd is not None:
            rfc822.dump(fd, "utf-8")
        else:
            return rfc822.dump(encoding="utf-8")
    
    def save(self):
        """
        Save this deb file if you have replaced its control
        """

        # control and its content

        control = self.control
        control_field = DebianPackage.get_control_content(control)

        # temporary control file

        temp_control = tempfile.NamedTemporaryFile(delete=False)
        temp_control.write(control_field.encode("utf-8"))
        temp_control.close()

        # Change permission of control file
        os.chmod(temp_control.name, 0o700)

        # copy temporary control tar gz from original debian package

        temp_control_tar_gz = tempfile.NamedTemporaryFile(delete=False)
        deb_handler = open(self.path, "rb")
        deb_handler.seek(self.offset_control + 60)
        orig_control_len = 0
        bytes_to_copy = self.length_control
        while orig_control_len < bytes_to_copy:
            bytes_left = bytes_to_copy - orig_control_len
            if bytes_left < 16 * 1024:
                bytes_to_read = bytes_left
            else:
                bytes_to_read = 16 * 1024  # 16k cache
            cache = deb_handler.read(bytes_to_read)
            if not cache:
                break
            orig_control_len = orig_control_len + bytes_to_read
            temp_control_tar_gz.write(cache)
        deb_handler.close()
        temp_control_tar_gz.close()

        # decompress original control tar gz to control tar

        temp_control_tar = tempfile.NamedTemporaryFile(delete=False)
        gz_control_tar_gz = gzip.open(temp_control_tar_gz.name, 'rb')
        temp_control_tar.write(gz_control_tar_gz.read())
        gz_control_tar_gz.close()
        temp_control_tar.close()

        # create temp new control tar file

        temp_new_control_tar = tempfile.NamedTemporaryFile(delete=False)
        temp_new_control_tar.close()

        def reset(tarinfo):
            tarinfo.uid = tarinfo.gid = 0
            tarinfo.uname = tarinfo.gname = "root"
            return tarinfo

        # copy with new control file

        new_control_tar = tarfile.open(temp_new_control_tar.name, "w:")
        new_control_tar.add(temp_control.name, "./control", filter=reset)
        orig_control_tar = tarfile.open(temp_control_tar.name, "r:")
        for orig_tarinfo_name in orig_control_tar.getnames():
            if orig_tarinfo_name == '.':
                continue
            elif orig_tarinfo_name == '..':
                continue
            elif orig_tarinfo_name == './control':
                continue
            elif orig_tarinfo_name == 'control':
                continue
            orig_tarinfo = orig_control_tar.getmember(orig_tarinfo_name)
            orig_tarinfo = reset(orig_tarinfo)
            orig_tarinfo_obj = orig_control_tar.extractfile(orig_tarinfo_name)
            if orig_tarinfo is None or orig_tarinfo_obj is None:
                continue
            new_control_tar.addfile(orig_tarinfo, orig_tarinfo_obj)
        orig_control_tar.close()
        new_control_tar.close()

        # compress new control tar to control tar gz

        temp_new_control_tar_gz = tempfile.NamedTemporaryFile(delete=False)
        temp_new_control_tar_gz.close()

        new_control_tar = open(temp_new_control_tar.name, 'rb')
        new_control_tar_gz = gzip.open(temp_new_control_tar_gz.name, "wb")
        while True:
            cache = new_control_tar.read(16 * 1024)  # 16k cache
            if not cache:
                break
            new_control_tar_gz.write(cache)
        new_control_tar.close()
        new_control_tar_gz.close()

        # build new debian package

        control_tar_size = int(os.path.getsize(new_control_tar_gz.name))

        # clean temporary control file

        os.unlink(temp_control.name)

        # new debian package

        new_deb = tempfile.NamedTemporaryFile(delete=False)

        # write debian header

        new_deb.write(
            b"\x21\x3C\x61\x72\x63\x68\x3E\x0A"  # 8
            b"\x64\x65\x62\x69\x61\x6E\x2D\x62"  # 16
            b"\x69\x6E\x61\x72\x79\x20\x20\x20"  # 24
        )
        new_deb.write(str(int(time.time())).ljust(12))
        new_deb.write(
            b"\x30\x20\x20\x20\x20\x20\x30\x20"  # 8
            b"\x20\x20\x20\x20\x31\x30\x30\x36"  # 16
            b"\x34\x34\x20\x20\x34\x20\x20\x20"  # 24
            b"\x20\x20\x20\x20\x20\x20\x60\x0A"  # 32
            b"\x32\x2E\x30\x0A\x63\x6F\x6E\x74"  # 40
            b"\x72\x6F\x6C\x2E\x74\x61\x72\x2E"  # 48
            b"\x67\x7A\x20\x20"  # 52
        )
        new_deb.write(str(int(time.time())).ljust(12))
        new_deb.write(
            b"\x30\x20\x20\x20\x20\x20\x30\x20"  # 8
            b"\x20\x20\x20\x20\x31\x30\x30\x36"  # 16
            b"\x34\x34\x20\x20"  # 20
        )
        new_deb.write(str(control_tar_size).ljust(10))
        new_deb.write(b"\x60\x0A")

        # write new control tar gz

        new_control_tar_gz = open(new_control_tar_gz.name, "rb")
        new_control_tar_gz.seek(0)
        while True:
            cache = new_control_tar_gz.read(16 * 1024)  # 16k cache
            if not cache:
                break
            new_deb.write(cache)
        new_control_tar_gz.close()

        # write control terminator

        if control_tar_size % 2 != 0:
            new_deb.write(b"\x0A")

        # write new data area

        deb_handler = open(self.path, "rb")
        deb_handler.seek(self.offset_data)
        orig_data_len = 0
        bytes_to_copy = self.length_data + 60
        while orig_data_len < bytes_to_copy:
            bytes_left = bytes_to_copy - orig_data_len
            if bytes_left < 16 * 1024:
                bytes_to_read = bytes_left
            else:
                bytes_to_read = 16 * 1024  # 16k cache
            cache = deb_handler.read(bytes_to_read)  # 16k cache
            if not cache:
                break
            orig_data_len = orig_data_len + bytes_to_read
            new_deb.write(cache)
        deb_handler.close()

        # save

        new_deb.close()

        # clean

        os.unlink(gz_control_tar_gz.filename)
        os.unlink(new_control_tar.name)
        os.unlink(new_control_tar_gz.name)
        os.unlink(self.path)

        """
        !!! To keep its path original !!!
        """
        # os.rename(new_deb.name, self.path)
        shutil.move(new_deb.name, self.path)

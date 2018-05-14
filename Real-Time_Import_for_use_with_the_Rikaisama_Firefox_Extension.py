# -*- coding: utf-8 -*-
#
#  Copyright (C) 2013-2015 Christopher Brochtrup
#
#  This file is part of Real-Time Import.
#
#  Real-Time Import is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Real-Time Import is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Real-Time Import.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
# Version: 1.3
# Contact: cb4960@gmail.com
###############################################################################

#### Includes ####

import os, re, codecs
import PyQt4.QtNetwork
import aqt
import anki
import base64
import hashlib
import inspect
import json
import os
import os.path
import re
import select
import socket
import sys
from time import time
from unicodedata import normalize

#
# General helpers
#

if sys.version_info[0] < 3:
    import urllib2
    web = urllib2

    from PyQt4.QtCore import QTimer
    from PyQt4.QtGui import QMessageBox
else:
    unicode = str

    from urllib import request
    web = request

    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QMessageBox

#### Configuration ####

# Listen on this port for incoming datagrams from Rikaisama
PORT = 49600

# True = allow duplicate notes to be added
ALLOW_DUPLICATES = False

# Debugging
DEBUG = True
LOG_FILE = os.path.join(aqt.mw.pm.base, "addons", "real_time_import.log");
CLEAR_LOG_AT_STARTUP = True


#### Code ####

# Note: This class was adapted from the Yomichan plugin by Alex Yatskov.
class Anki:
    def addNote(self, deckName, modelName, fields, tags=list()):
        note = self.createNote(deckName, modelName, fields, tags)
        if note is not None:
            collection = self.collection()
            self.window().checkpoint("Add Note from Real-Time Import")
            collection.addNote(note)
            collection.autosave()
            showTooltip("Note added.", 1000);
            writeLog("Note added.")
            return note.id


    def canAddNote(self, deckName, modelName, fields):
        return bool(self.createNote(deckName, modelName, fields))


    def createNote(self, deckName, modelName, fields, tags=list()):
        model = self.models().byName(modelName)
        if model is None:
            return None

        deck = self.decks().byName(deckName)
        if deck is None:
            return None

        note = anki.notes.Note(self.collection(), model)
        note.model()['did'] = deck['id']
        note.tags = tags

        try:
            for name, value in fields.items():
                note[name] = value
        except:
            showTooltip("Error, current note type does not contain the following field: '" + name + "'", 5000);
            writeLog("Anki.createNote: Error, current note type does not contain the following field: '" + name + "'")
            return None

        dupOrEmpty = note.dupeOrEmpty()

        if dupOrEmpty == 1:
            showTooltip("Error, first field in note is empty!");
            writeLog("Anki.createNote: first field in note is empty!")
            return note
        elif dupOrEmpty == 2 and not ALLOW_DUPLICATES:
            showTooltip("Error, duplicate note!");
            writeLog("Anki.createNote: Error, duplicate note!")
        else:
            return note


    def browseNote(self, noteId):
        browser = aqt.dialogs.open('Browser', self.window())
        browser.form.searchEdit.lineEdit().setText('nid:{0}'.format(noteId))
        browser.onSearch()


    def startEditing(self):
        self.window().requireReset()


    def stopEditing(self):
        if self.collection():
            self.window().maybeReset()


    def window(self):
        return aqt.mw


    def addUiAction(self, action):
        self.window().form.menuTools.addAction(action)


    def collection(self):
        return self.window().col


    def models(self):
        return self.collection().models


    def modelNames(self):
        return self.models().allNames()


    def modelFieldNames(self, modelName):
        model = self.models().byName(modelName)
        if model is not None:
            return [field['name'] for field in model['flds']]


    def decks(self):
        return self.collection().decks


    def deckNames(self):
        return self.decks().allNames()


    def curModelID(self):
        return self.collection().conf['curModel']


    def curDeckID(self):
        return self.collection().conf['curDeck']


    def curModel(self):
        return self.models().get(self.curModelID())


    def curDeck(self):
        return self.decks().get(self.curDeckID())


    def curModelName(self):
        return self.curModel()['name']


    def curDeckName(self):
        return self.curDeck()['name']


class MessageCommand():
    def __init__(self, filename):
        writeLog("MessageCommand.__init__: START")
        self.anki = Anki()
        self.version = None
        self.command = None
        self.fieldNames = []
        self.tags = []

        try:
            self.file = codecs.open(filename, "r", "utf-8-sig")
        except:
            showTooltip("Error, unable to open \"" + filename + "\"");
            writeLog("MessageCommand.__init__: Unable to open \"" + filename + "\"")
            return
        if self.parseHeader():
            self.performCommand()
        self.file.close()


    def performCommand(self):
        writeLog("MessageCommand.performCommand: START")
        if self.command == "add":
            self.doAdd()
        else:
            showTooltip("Error, invalid command = " + self.command);
            writeLog("MessageCommand.performCommand: Invalid command = " + self.command)


    def doAdd(self):
        writeLog("MessageCommand.doAdd: START")
        if self.version == "1":
            self.parseFieldNames()
            if len(self.fieldNames) > 0 and len(self.fieldNames[0]) > 0:
                self.parseTags()
                for line in self.file:
                    writeLog("MessageCommand.doAdd: line = " + line.strip('\r\n '))
                    self.addLineToDeck(line.strip('\r\n '))
            else:
                showTooltip("Error, no field names specified!");
                writeLog("MessageCommand.doAdd: No field names specified")
        else:
            writeLog("MessageCommand.doAdd: Unsupported version = " + self.version)


    def parseHeader(self):
        status = True
        # Get the command and command version
        try:
            items = re.split("\t", self.file.readline())
            self.command = items[0].strip().lower()
            self.version = items[1].strip()
            writeLog("MessageCommand.parseHeader: command = " + unicode(self.command))
            writeLog("MessageCommand.parseHeader: version = " + unicode(self.version))
        except:
            showTooltip("Error, invalid header line!");
            writeLog("MessageCommand.parseHeader: Invalid header line")
            status = False
        return status


    def parseFieldNames(self):
        # Get the field names
        self.fieldNames = re.split("\t", self.file.readline())
        self.fieldNames = [i.strip() for i in self.fieldNames] # strip
        writeLog("MessageCommand.parseFieldNames: fieldNames = " + unicode(self.fieldNames))


    def parseTags(self):
        # Get the tags
        self.tags = re.split(" ", self.file.readline())
        self.tags = [i.strip() for i in self.tags] # strip
        writeLog("MessageCommand.parseTags: tags = \"" + unicode(self.tags) + "\"")


    def addLineToDeck(self, line):
        # Get the field contents
        fields = re.split("\t", line)

        # Does line contain the correct # of fields (according to given field names)?
        if len(fields) >= len(self.fieldNames):

            # Make a dictionary in the format {field_name: field_contents}
            ankiFieldInfo = {}
            for i in range(len(fields)):
                ankiFieldInfo[self.fieldNames[i]] = fields[i].strip()

            writeLog("MessageCommand.addLineToDeck: ankiFieldInfo = " + unicode(ankiFieldInfo))

            # Try to add the card to the deck
            noteId = self.anki.addNote(self.anki.curDeckName(), self.anki.curModelName(),
                ankiFieldInfo, self.tags)

            # Anki won't add the card if duplicate, fields names are incorrect, etc.
            if not noteId:
                writeLog("MessageCommand.addLineToDeck: Could not add to deck!")
        else:
            showTooltip("Error, too few fields, line not added!");
            writeLog("MessageCommand.addLineToDeck: Too few fields, line not added!")


def clearLog():
    if DEBUG:
        file = codecs.open(LOG_FILE, "w", "utf-8-sig")
        file.write("")
        file.close()


def writeLog(text):
    if DEBUG:
        file = codecs.open(LOG_FILE, "a", "utf-8-sig")
        file.write(text + "\n")
        file.close()


def showTooltip(text, timeOut=3000):
    aqt.utils.tooltip("<b>Real-Time Import</b><br />" + text, timeOut)


def processPendingDatagrams():
    writeLog("processPendingDatagrams: START")
    datagram, host, port = udpSocket.readDatagram(udpSocket.pendingDatagramSize())
    filename = unicode(datagram.strip())
    writeLog("processPendingDatagrams: filename = " + filename)

    # Don't add if in deck browser (Note: it will work, but might be confusing)
    if aqt.mw.state != "deckBrowser":
        msgCmd = MessageCommand(filename);
    else:
        showTooltip("Error, you must open a deck first!");


#### Main ####

if CLEAR_LOG_AT_STARTUP:
    clearLog()

writeLog("-----------------------------------------------------------")
writeLog("Main: START")

try:
   udpSocket = PyQt4.QtNetwork.QUdpSocket()
   udpSocket.bind(PORT);
   udpSocket.readyRead.connect(processPendingDatagrams)
except:
   writeLog("Main: Could not setup connection!")



API_VERSION = 5
TICK_INTERVAL = 25
URL_TIMEOUT = 10
# URL_UPGRADE = 'https://raw.githubusercontent.com/FooSoft/anki-connect/master/AnkiConnect.py'
NET_ADDRESS = os.getenv('ANKICONNECT_BIND_ADDRESS', '127.0.0.1')
NET_BACKLOG = 5
NET_PORT = 49601


def makeBytes(data):
    return data.encode('utf-8')


def makeStr(data):
    return data.decode('utf-8')

#
# AjaxRequest
#
class AjaxRequest:
    def __init__(self, headers, body):
        self.headers = headers
        self.body = body


#
# AjaxClient
#
class AjaxClient:
    def __init__(self, sock, handler):
        self.sock = sock
        self.handler = handler
        self.readBuff = bytes()
        self.writeBuff = bytes()


    def advance(self, recvSize=1024):
        if self.sock is None:
            return False

        rlist, wlist = select.select([self.sock], [self.sock], [], 0)[:2]

        if rlist:
            msg = self.sock.recv(recvSize)
            if not msg:
                self.close()
                return False

            self.readBuff += msg

            req, length = self.parseRequest(self.readBuff)
            if req is not None:
                self.readBuff = self.readBuff[length:]
                self.writeBuff += self.handler(req)

        if wlist and self.writeBuff:
            length = self.sock.send(self.writeBuff)
            self.writeBuff = self.writeBuff[length:]
            if not self.writeBuff:
                self.close()
                return False

        return True


    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

        self.readBuff = bytes()
        self.writeBuff = bytes()


    def parseRequest(self, data):
        parts = data.split(makeBytes('\r\n\r\n'), 1)
        if len(parts) == 1:
            return None, 0

        headers = {}
        for line in parts[0].split(makeBytes('\r\n')):
            pair = line.split(makeBytes(': '))
            headers[pair[0].lower()] = pair[1] if len(pair) > 1 else None

        headerLength = len(parts[0]) + 4
        bodyLength = int(headers.get(makeBytes('content-length'), 0))
        totalLength = headerLength + bodyLength

        if totalLength > len(data):
            return None, 0

        body = data[headerLength : totalLength]
        return AjaxRequest(headers, body), totalLength

#
# AjaxServer
#
class AjaxServer:
    def __init__(self, handler):
        self.handler = handler
        self.clients = []
        self.sock = None
        self.resetHeaders()


    def setHeader(self, name, value):
        self.extraHeaders[name] = value


    def resetHeaders(self):
        self.headers = [
            ['HTTP/1.1 200 OK', None],
            ['Content-Type', 'text/json'],
            ['Access-Control-Allow-Origin', '*']
        ]
        self.extraHeaders = {}


    def getHeaders(self):
        headers = self.headers[:]
        for name in self.extraHeaders:
            headers.append([name, self.extraHeaders[name]])
        return headers


    def advance(self):
        if self.sock is not None:
            self.acceptClients()
            self.advanceClients()


    def acceptClients(self):
        rlist = select.select([self.sock], [], [], 0)[0]
        if not rlist:
            return

        clientSock = self.sock.accept()[0]
        if clientSock is not None:
            clientSock.setblocking(False)
            self.clients.append(AjaxClient(clientSock, self.handlerWrapper))


    def advanceClients(self):
        self.clients = list(filter(lambda c: c.advance(), self.clients))


    def listen(self):
        self.close()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setblocking(False)
        self.sock.bind((NET_ADDRESS, NET_PORT))
        self.sock.listen(NET_BACKLOG)


    def handlerWrapper(self, req):
        if len(req.body) == 0:
            body = makeBytes('AnkiConnect v.{}'.format(API_VERSION))
        else:
            try:
                params = json.loads(makeStr(req.body))
                body = makeBytes(json.dumps(self.handler(params)))
            except ValueError:
                body = makeBytes(json.dumps(None))

        resp = bytes()

        self.setHeader('Content-Length', str(len(body)))
        headers = self.getHeaders()

        for key, value in headers:
            if value is None:
                resp += makeBytes('{}\r\n'.format(key))
            else:
                resp += makeBytes('{}: {}\r\n'.format(key, value))

        resp += makeBytes('\r\n')
        resp += body

        return resp


    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

        for client in self.clients:
            client.close()

        self.clients = []

class TcpServer:
    def __init__(self):
        self.server = AjaxServer(self.handler)

        try:
            self.server.listen()

            self.timer = QTimer()
            self.timer.timeout.connect(self.advance)
            self.timer.start(TICK_INTERVAL)
        except:
            QMessageBox.critical(
                self.anki.window(),
                'AnkiConnect',
                'Failed to listen on port {}.\nMake sure it is available and is not in use.'.format(NET_PORT)
            )


    def advance(self):
        self.server.advance()


    def handler(self, request):
        name = request.get('action', '')
        version = request.get('version', 4)
        params = request.get('params', {})
        reply = {'result': 'Test', 'error': None}

        try:
            # Method Calls Here
            reply['result'] = { 'action': name }
        except Exception as e:
            reply['error'] = str(e)

        if version > 4:
            return reply
        else:
            return reply['result']

connect = TcpServer()
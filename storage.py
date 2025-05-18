# [<user_id,text,used>,<user_id,text,uesd>]
# 沒用過的是false
descriptions_of_music = []
# false 是停下 true 是播放
play_mode = True

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

class VoiceClientManager:
    def __init__(self):
        self._voice_client = None
        self._lock = threading.Lock()
        self._connected_event = asyncio.Event()
        self._loop = None
        
    def _set_event_loop(self, loop):
        self._loop = loop
            
    @property
    def voice_client(self):
        with self._lock:
            return self._voice_client
            
    @voice_client.setter
    def voice_client(self, client):
        with self._lock:
            self._voice_client = client
            if client is not None and client.is_connected():
                if not self._connected_event.is_set():
                    asyncio.run_coroutine_threadsafe(self._set_connected(), self._loop)
            else:
                if self._connected_event.is_set():
                    asyncio.run_coroutine_threadsafe(self._clear_connected(), self._loop)
    
    async def _set_connected(self):
        self._connected_event.set()
        
    async def _clear_connected(self):
        self._connected_event.clear()
    
    async def wait_for_voice_client(self, timeout=5.0):
        """異步等待 voice_client"""
        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout)
            return self.voice_client
        except asyncio.TimeoutError:
            return None
    
    def is_connected(self):
        client = self.voice_client
        try:
            return client is not None and client.is_connected()
        except:
            return False
            
    def get_voice_client(self):
        """安全地獲取 voice_client"""
        with self._lock:
            if self._voice_client is None:
                return None
            try:
                if not self._voice_client.is_connected():
                    return None
                return self._voice_client
            except:
                return None

# 創建全局實例
voice_manager = VoiceClientManager()
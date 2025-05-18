from audiocraft.models import MusicGen
from audiocraft.data.audio import audio_write
import numpy as np
import asyncio
import time
import os
from discord import FFmpegPCMAudio
import sys
from pathlib import Path
import tempfile
import torch
import storage
from queue import Queue
from concurrent.futures import ThreadPoolExecutor

class AsyncMusicGenerator:
    def __init__(self, description, model, initial_duration=8):
        self.description = description
        self.model = model
        self.sample_rate = model.sample_rate
        self.initial_duration = initial_duration
        self.playing = False
        self.audio_queue = asyncio.Queue(maxsize=3)
        self.last_segment = None
        self.save_counter = 0
        
        # 設置 FFmpeg 路徑
        if sys.platform == 'win32':
            self.ffmpeg_path = str(Path.home() / 'AppData' / 'Local' / 'Programs' / 'ffmpeg' / 'bin' / 'ffmpeg.exe')
            if not os.path.exists(self.ffmpeg_path):
                self.ffmpeg_path = 'ffmpeg'
        else:
            self.ffmpeg_path = 'ffmpeg'
            
        # 用於在執行緒池中運行 CPU 密集型操作
        self.executor = ThreadPoolExecutor(max_workers=2)

    def _generate_audio(self, prompt):
        """在執行緒池中運行的同步音頻生成函數"""
        self.model.set_generation_params(duration=self.initial_duration)
        generated = self.model.generate([prompt])
        wav = generated[0].cpu().numpy()
        if wav.ndim > 1:
            wav = wav[0] if wav.shape[0] <= 2 else wav[:, 0]
        return wav.flatten()

    async def generate_initial_audio(self):
        """異步生成初始音頻"""
        print(f"為 '{self.description}' 生成初始音頻...")
        loop = asyncio.get_running_loop()
        wav = await loop.run_in_executor(self.executor, self._generate_audio, self.description)
        
        # 保存音頻
        audio_write(f'{self.description.replace(" ", "_")}_initial', 
                   torch.tensor(wav).reshape(1, -1), 
                   self.sample_rate, 
                   strategy="loudness")
                   
        self.last_segment = wav
        await self.audio_queue.put(wav)
        return wav

    async def _generate_continuation(self):
        """異步生成連續的音頻"""
        try:
            while self.playing:
                if self.audio_queue.qsize() >= 3:
                    await asyncio.sleep(1)
                    continue
                    
                print(f"\n為 '{self.description}' 生成新的音頻...")
                loop = asyncio.get_running_loop()
                new_wav = await loop.run_in_executor(self.executor, self._generate_audio, self.description)
                
                self.save_counter += 1
                audio_write(f'{self.description.replace(" ", "_")}_evolved_{self.save_counter}', 
                          torch.tensor(new_wav).reshape(1, -1), 
                          self.sample_rate, 
                          strategy="loudness")
                          
                self.last_segment = new_wav
                await self.audio_queue.put(new_wav)
                print(f"已生成新的音頻片段 #{self.save_counter}")
                
        except Exception as e:
            print(f"音頻生成錯誤: {str(e)}")

    async def _playback_loop(self):
        """異步播放循環"""
        try:
            while self.playing:
                if not self.audio_queue.empty():
                    next_audio = await self.audio_queue.get()
                    print(f"\n開始播放 '{self.description}' 的新音頻片段...")

                    # 儲存成暫存 wav 檔
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmpfile:
                        path = tmpfile.name
                        path = os.path.abspath(path)
                        audio_write(path[:-4],
                                  torch.tensor(next_audio).reshape(1, -1),
                                  self.sample_rate,
                                  strategy="loudness")

                    try:
                        if not os.path.exists(path):
                            print(f"錯誤：音頻文件不存在：{path}")
                            continue

                        # 重試機制
                        max_retries = 5
                        retry_count = 0
                        
                        while retry_count < max_retries and self.playing:
                            try:
                                print(f"嘗試播放音頻（第 {retry_count + 1} 次嘗試）")
                                voice_client = storage.voice_manager.get_voice_client()
                                
                                if not voice_client or not voice_client.is_connected():
                                    print("等待 voice_client 就緒...")
                                    await asyncio.sleep(2)
                                    retry_count += 1
                                    continue

                                # 等待當前音頻播放完成
                                while voice_client.is_playing():
                                    await asyncio.sleep(1)
                                    if not self.playing:
                                        break

                                if not self.playing:
                                    break

                                # 播放新音頻
                                audio_source = FFmpegPCMAudio(path, executable=self.ffmpeg_path)
                                voice_client.play(audio_source)
                                print("✅ 音頻開始播放")

                                # 等待播放完成
                                while voice_client.is_playing() and self.playing:
                                    await asyncio.sleep(1)

                                print(f"'{self.description}' 音頻片段播放完成")
                                break

                            except Exception as e:
                                print(f"播放錯誤: {e}")
                                retry_count += 1
                                if retry_count < max_retries:
                                    await asyncio.sleep(2)

                        if retry_count >= max_retries:
                            print("❌ 達到最大重試次數，跳過此音頻片段")

                    finally:
                        # 清理暫存檔
                        try:
                            os.remove(path)
                        except Exception as e:
                            print(f"無法刪除暫存音檔: {e}")

                await asyncio.sleep(0.5)

        except Exception as e:
            print(f"播放循環錯誤: {e}")

    async def start(self):
        """開始音樂生成和播放"""
        if self.playing:
            return
            
        self.playing = True
        await self.generate_initial_audio()
        
        # 創建並啟動生成和播放任務
        self.generation_task = asyncio.create_task(self._generate_continuation())
        self.playback_task = asyncio.create_task(self._playback_loop())
        
        print(f"已啟動 '{self.description}' 的音樂生成")

    async def stop(self):
        """停止音樂生成和播放"""
        self.playing = False
        
        # 停止 Discord 的 voice_client 播放
        voice_client = storage.voice_manager.get_voice_client()
        if voice_client and voice_client.is_playing():
            voice_client.stop()
            
        # 等待任務完成
        if hasattr(self, 'generation_task'):
            try:
                await asyncio.wait_for(self.generation_task, timeout=2)
            except asyncio.TimeoutError:
                pass
                
        if hasattr(self, 'playback_task'):
            try:
                await asyncio.wait_for(self.playback_task, timeout=2)
            except asyncio.TimeoutError:
                pass
                
        print(f"已停止 '{self.description}' 的音樂生成")

# ========= 主程式區塊 =========

async def music_player_loop():
    print("初始化 MusicGen 模型...")
    model = MusicGen.get_pretrained("small")
    
    generators = {}
    active_descriptions = set()
    
    print("進入主循環，監聽 storage 狀態...")
    
    try:
        while True:
            if storage.play_mode:
                for i, (user_id, desc, used) in enumerate(storage.descriptions_of_music):
                    if not used and desc not in generators:
                        print(f"\n🎧 為使用者 {user_id} 播放新的音樂描述: '{desc}'")
                        gen = AsyncMusicGenerator(
                            description=desc,
                            model=model,
                            initial_duration=8
                        )
                        generators[desc] = gen
                        await gen.start()
                        active_descriptions.add(desc)
                        storage.descriptions_of_music[i] = (user_id, desc, True)
            else:
                if active_descriptions:
                    print("\n🛑 偵測到 storage.play_mode=False，停止所有音樂...")
                    for desc in list(active_descriptions):
                        await generators[desc].stop()
                        del generators[desc]
                        active_descriptions.remove(desc)
                        
            await asyncio.sleep(1)
            
    except asyncio.CancelledError:
        print("🔚 收到取消訊號，正在停止所有生成器...")
        for gen in generators.values():
            await gen.stop()
        print("✅ 所有音樂生成器已停止。")
import asyncio
from discord_bot import run_discord_bot
from music_gen import music_player_loop
import storage

async def main():
    # 獲取事件循環
    loop = asyncio.get_running_loop()
    storage.voice_manager._set_event_loop(loop)
    
    # 創建兩個異步任務
    task1 = asyncio.create_task(run_discord_bot())
    task2 = asyncio.create_task(music_player_loop())
    
    # 等待兩個任務完成（實際上它們會一直運行）
    try:
        await asyncio.gather(task1, task2)
    except KeyboardInterrupt:
        print("程序接收到終止信號，正在關閉...")
        # 確保停止所有音樂生成
        storage.play_mode = False
    except Exception as e:
        print(f"發生錯誤: {e}")
    finally:
        # 確保清理任何資源
        storage.play_mode = False
        if storage.voice_manager.voice_client:
            try:
                await storage.voice_manager.voice_client.disconnect()
            except:
                pass
        print("正在清理資源...")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("程序接收到終止信號，已關閉")
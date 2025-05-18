import discord
import os
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from discord import FFmpegPCMAudio
import storage
import asyncio

# 為方便管理，將TOKEN寫在.env檔案裡，並用dotenv調用
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
SERVER_ID = int(os.getenv("DISCORD_SERVER_ID"))
GUILD_ID = discord.Object(id=SERVER_ID)

# 創建許可權物件
intents = discord.Intents.default()
# 接發訊息權限
intents.message_content = True
# 添加語音相關權限
intents.voice_states = True
intents.guilds = True
# 創建機器人實例
bot = commands.Bot(command_prefix="!", intents=intents)

# 創建一個/命令 叫/describe
@bot.tree.command(name="describe", description="描述你希望聽到的音樂", guild=GUILD_ID)
@app_commands.describe(text="你要描述的東西是什麼？")
async def describe(interaction: discord.Interaction, text: str):
    #                           用戶id，描述，尚未被生成
    storage.descriptions_of_music.append((interaction.user.id, text, False))
    # 回覆私密訊息
    await interaction.response.send_message(f"你描述的是：{text}", ephemeral=True)


@bot.tree.command(name="list_descriptions", description="列出目前的描述", guild=GUILD_ID)
async def list_descriptions(interaction: discord.Interaction):
    msg = "\n".join([f"{i+1}. {desc[1]}（used={desc[2]}）" for i, desc in enumerate(storage.descriptions_of_music)])
    if not msg:
        msg = "目前沒有任何描述"
    await interaction.response.send_message(f"目前儲存的描述：\n{msg}", ephemeral=True)
    

@bot.tree.command(name="play_mode", description="設定播放模式", guild=GUILD_ID)
@app_commands.describe(mode="True 是播放，False 是暫停")
async def play_mode(interaction: discord.Interaction, mode: bool):
    # 存起來(在 storage.py 裡定義了 play_mode 變數）
    storage.play_mode = mode

    # 根據布林值判斷
    if not mode:
        await interaction.response.send_message(
            f"{interaction.user.mention} 已暫停播放音樂。",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"{interaction.user.mention} 繼續播放音樂。",
            ephemeral=True
        )


@bot.tree.command(name="connect", description="讓機器人加入你的語音頻道", guild=GUILD_ID)
async def connect(interaction: discord.Interaction):
    # 取得使用者目前所在的語音頻道
    voice_state = interaction.user.voice

    if voice_state is None or voice_state.channel is None:
        await interaction.response.send_message("⚠️ 你必須先加入一個語音頻道！", ephemeral=True)
        return

    channel = voice_state.channel
    
    print(f"準備連接到語音頻道：{channel.name}")
    print(f"目前 voice_client 狀態：{storage.voice_manager.get_voice_client()}")

    # 加入語音頻道
    try:
        # 檢查是否已經連接到目標頻道
        current_client = storage.voice_manager.get_voice_client()
        if current_client and current_client.channel.id == channel.id:
            print(f"已經連接到目標頻道：{channel.name}")
            await interaction.response.send_message(f"✅ 已在語音頻道：{channel.name}", ephemeral=True)
            return

        # 如果機器人已經在某個語音頻道中，先斷開連接
        if current_client:
            try:
                print(f"斷開與頻道 {current_client.channel.name} 的連接")
                await current_client.disconnect(force=True)
            except:
                pass
            storage.voice_manager.voice_client = None
            await asyncio.sleep(1)  # 等待斷開連接完成
            
        # 嘗試連接新的語音頻道
        print(f"嘗試連接到頻道：{channel.name}")
        try:
            new_client = await channel.connect(timeout=60, reconnect=True)
            print(f"成功創建新的語音連接")
            storage.voice_manager.voice_client = new_client
            await asyncio.sleep(1)  # 等待連接完成
            
            # 驗證連接狀態
            if storage.voice_manager.is_connected():
                print(f"✅ 成功連接到語音頻道：{channel.name}")
                await interaction.response.send_message(f"✅ 已加入語音頻道：{channel.name}", ephemeral=True)
            else:
                raise Exception("連接狀態驗證失敗")
                
        except Exception as e:
            print(f"❌ 連接嘗試失敗：{str(e)}")
            # 嘗試清理並重試一次
            try:
                if channel.guild.voice_client:
                    await channel.guild.voice_client.disconnect(force=True)
                await asyncio.sleep(1)
                new_client = await channel.connect(timeout=60, reconnect=True)
                storage.voice_manager.voice_client = new_client
                print(f"✅ 重試成功")
                await interaction.response.send_message(f"✅ 已加入語音頻道：{channel.name}", ephemeral=True)
            except Exception as retry_error:
                print(f"❌ 重試也失敗了：{str(retry_error)}")
                storage.voice_manager.voice_client = None
                await interaction.response.send_message(f"❌ 連接失敗：{str(e)}", ephemeral=True)
            
    except Exception as e:
        print(f"❌ 連接錯誤：{str(e)}")
        print(f"錯誤類型：{type(e)}")
        import traceback
        print(f"詳細錯誤信息：{traceback.format_exc()}")
        storage.voice_manager.voice_client = None
        await interaction.response.send_message(f"❌ 加入失敗：{str(e)}", ephemeral=True)


@bot.tree.command(name="disconnect", description="讓機器人離開語音頻道", guild=GUILD_ID)
async def disconnect(interaction: discord.Interaction):
    if storage.voice_manager.is_connected():
        await storage.voice_manager.voice_client.disconnect()
        storage.voice_manager.voice_client = None
        await interaction.response.send_message("✅ 已離開語音頻道", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ 機器人目前不在任何語音頻道中。", ephemeral=True)


# 當機器人上線時執行
@bot.event 
async def on_ready():
    try:
        # 設置事件循環
        storage.voice_manager._set_event_loop(asyncio.get_running_loop())
        
        # 同步指令
        synced = await bot.tree.sync(guild=GUILD_ID)
        print(f"✅ 已同步 {len(synced)} 個指令到 Guild {GUILD_ID}")
        
        # 檢查同步後的指令
        commands = await bot.tree.fetch_commands(guild=GUILD_ID)
        if commands:
            for cmd in commands:
                print(f"📌 已同步指令：/{cmd.name}")
        else:
            print("⚠️ 警告：同步後沒有指令")
            
        # 檢查並重置語音連接狀態
        if storage.voice_manager.voice_client:
            try:
                if storage.voice_manager.is_connected():
                    await storage.voice_manager.voice_client.disconnect()
            except:
                pass
            storage.voice_manager.voice_client = None
            print("🔄 已重置語音連接狀態")
            
    except Exception as e:
        print(f"❌ 同步失敗: {e}")
        
    print(f"🤖 機器人已登入為 {bot.user}")


@bot.event
async def on_voice_state_update(member, before, after):
    # 如果是機器人自己的狀態改變
    if member.id == bot.user.id:
        print(f"Bot 語音狀態更新：{'已連接' if after.channel else '已斷開'}")
        
        # 如果機器人被移出語音頻道
        if before.channel and not after.channel:
            print("Bot 已離開語音頻道，重置 voice_client")
            storage.voice_manager.voice_client = None
            
        # 如果機器人加入新的語音頻道
        elif after.channel:
            print(f"Bot 已加入語音頻道：{after.channel.name}")
            # 確保 voice_client 狀態正確
            current_client = storage.voice_manager.get_voice_client()
            if current_client:
                if current_client.channel.id != after.channel.id:
                    try:
                        await current_client.disconnect(force=True)
                        storage.voice_manager.voice_client = None
                    except:
                        pass
            
            # 等待一下確保連接已經建立
            await asyncio.sleep(1)
            
            # 更新 voice_client
            try:
                guild = after.channel.guild
                if guild.voice_client and guild.voice_client.is_connected():
                    storage.voice_manager.voice_client = guild.voice_client
                    print("✅ 已更新 voice_client")
                else:
                    new_client = await after.channel.connect()
                    storage.voice_manager.voice_client = new_client
                    print("✅ 已建立新的語音連接")
            except Exception as e:
                print(f"❌ 連接失敗：{e}")
                storage.voice_manager.voice_client = None


# 執行
async def run_discord_bot():
    await bot.start(TOKEN)
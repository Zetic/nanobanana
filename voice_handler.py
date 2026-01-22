"""
Voice handler module for speech-to-speech interaction using XAI's Grok Voice API.
This module handles:
- Voice channel connection management
- Audio streaming to/from XAI Realtime API via WebSocket
- Audio playback using FFmpeg
- Voice input capture using discord-ext-voice-recv
"""

import asyncio
import base64
import json
import logging
import struct
import io
import time
from datetime import datetime
from typing import Optional, Dict, Any, Callable, List, Tuple
from collections import deque, defaultdict

import discord
from discord import VoiceClient
import websockets
from websockets.protocol import State as WebSocketState

# Import voice receive extension
try:
    from discord.ext import voice_recv
    VOICE_RECV_AVAILABLE = True
except ImportError:
    VOICE_RECV_AVAILABLE = False

# Import Opus error for specific error handling
try:
    from discord.opus import OpusError
except ImportError:
    # Create a custom OpusError class if discord.opus.OpusError is not importable
    # This can happen if discord.py is installed but opus libraries are missing,
    # or in testing environments without full discord.py installation
    # Note: The actual discord.opus.OpusError may have different behavior,
    # but this fallback allows the code to function in such environments
    class OpusError(Exception):
        """Custom OpusError for when discord.opus.OpusError is not available."""
        pass

import config
from model_interface import get_model_generator

logger = logging.getLogger(__name__)

# Default model for voice image generation
DEFAULT_VOICE_IMAGE_MODEL = "nanobanana"

# XAI Realtime API WebSocket URL
XAI_REALTIME_URL = "wss://api.x.ai/v1/realtime"

# Audio format constants for Discord (48kHz, 16-bit PCM, stereo)
DISCORD_SAMPLE_RATE = 48000
DISCORD_CHANNELS = 2
DISCORD_SAMPLE_WIDTH = 2  # 16-bit = 2 bytes

# Audio format constants for XAI Realtime API (16kHz, 16-bit PCM, mono)
XAI_SAMPLE_RATE = 16000
XAI_CHANNELS = 1
XAI_SAMPLE_WIDTH = 2  # 16-bit = 2 bytes

# Buffer sizes
AUDIO_BUFFER_SIZE = 3200  # 200ms of audio at 16kHz


class AudioResampler:
    """Simple audio resampler for converting between sample rates."""
    
    @staticmethod
    def resample_48k_stereo_to_16k_mono(audio_data: bytes) -> bytes:
        """
        Convert Discord audio (48kHz stereo) to XAI format (16kHz mono).
        
        Args:
            audio_data: Raw PCM audio bytes (48kHz, 16-bit, stereo)
            
        Returns:
            Resampled PCM audio bytes (16kHz, 16-bit, mono)
        """
        if not audio_data:
            return b''
        
        # Unpack as 16-bit signed integers
        num_samples = len(audio_data) // 2
        samples = struct.unpack(f'<{num_samples}h', audio_data)
        
        # Convert stereo to mono by averaging channels
        mono_samples = []
        for i in range(0, len(samples), 2):
            if i + 1 < len(samples):
                avg = (samples[i] + samples[i + 1]) // 2
                mono_samples.append(avg)
        
        # Downsample from 48kHz to 16kHz (take every 3rd sample)
        downsampled = mono_samples[::3]
        
        # Pack back to bytes
        return struct.pack(f'<{len(downsampled)}h', *downsampled)
    
    @staticmethod
    def resample_16k_mono_to_48k_stereo(audio_data: bytes) -> bytes:
        """
        Convert XAI audio (16kHz mono) to Discord format (48kHz stereo).
        
        Args:
            audio_data: Raw PCM audio bytes (16kHz, 16-bit, mono)
            
        Returns:
            Resampled PCM audio bytes (48kHz, 16-bit, stereo)
        """
        if not audio_data:
            return b''
        
        # Unpack as 16-bit signed integers
        num_samples = len(audio_data) // 2
        samples = struct.unpack(f'<{num_samples}h', audio_data)
        
        # Upsample from 16kHz to 48kHz: triplicate each sample (3x)
        # Convert mono to stereo: duplicate each upsampled sample for L and R channels (2x)
        # Total: each original sample becomes 6 samples
        # This gives us: 16kHz mono -> 48kHz stereo
        stereo_upsampled = []
        for sample in samples:
            # 6 values per sample: 3 for upsampling * 2 for stereo channels
            stereo_upsampled.extend([sample, sample, sample, sample, sample, sample])
        
        # Pack back to bytes
        return struct.pack(f'<{len(stereo_upsampled)}h', *stereo_upsampled)


class XAIRealtimeSession:
    """Manages a WebSocket connection to XAI's Grok Realtime API."""
    
    def __init__(self, on_audio_response: Callable[[bytes], None], on_text_response: Optional[Callable[[str], None]] = None, on_image_generated: Optional[Callable[[Any, str], None]] = None):
        """
        Initialize the XAI Realtime session.
        
        Args:
            on_audio_response: Callback function to handle audio response data
            on_text_response: Optional callback for text transcription responses
            on_image_generated: Optional callback when an image is generated (image, prompt)
        """
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.on_audio_response = on_audio_response
        self.on_text_response = on_text_response
        self.on_image_generated = on_image_generated
        self._running = False
        self._receive_task: Optional[asyncio.Task] = None
        self._audio_buffer = bytearray()
        self._response_in_progress = False
        
    async def connect(self) -> tuple[bool, Optional[str]]:
        """
        Establish WebSocket connection to XAI Realtime API.
        
        Returns:
            Tuple of (True, None) if connection successful, or (False, error_reason) on failure
        """
        if not config.XAI_API_KEY:
            error_msg = "XAI_API_KEY not configured"
            logger.error(error_msg)
            return False, error_msg
        
        try:
            # Build URL with model parameter
            url = f"{XAI_REALTIME_URL}?model={config.XAI_VOICE_MODEL}"
            logger.info(f"Connecting to XAI Realtime API: {url}")
            
            # Connect with API key in header
            headers = {
                "Authorization": f"Bearer {config.XAI_API_KEY}"
            }
            
            self.websocket = await websockets.connect(
                url,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=30
            )
            
            self._running = True
            
            # Configure the session
            await self._configure_session()
            
            # Start receiving messages
            self._receive_task = asyncio.create_task(self._receive_loop())
            
            logger.info("Connected to XAI Realtime API")
            return True, None
            
        except websockets.exceptions.InvalidStatusCode as e:
            error_msg = f"XAI API returned invalid status code {e.status_code}"
            logger.error(error_msg)
            return False, error_msg
        except websockets.exceptions.WebSocketException as e:
            error_msg = f"WebSocket connection error: {type(e).__name__}: {e}"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"XAI connection error: {type(e).__name__}: {e}"
            logger.error(error_msg)
            return False, error_msg
    
    async def _configure_session(self):
        """Send session configuration to XAI."""
        config_event = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": "You are a helpful voice assistant in a Discord voice chat called ZPT. Keep responses concise and conversational. Be friendly and engaging.",
                "voice": config.XAI_VOICE,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.3,
                    "prefix_padding_ms": 200,
                    "silence_duration_ms": 300
                }
            }
        }
        
        await self._send_event(config_event)
        logger.info("Sent session configuration to XAI")
    
    async def _send_event(self, event: Dict[str, Any]):
        """Send an event to the XAI WebSocket."""
        if self.websocket and self.websocket.state == WebSocketState.OPEN:
            try:
                await self.websocket.send(json.dumps(event))
            except Exception as e:
                logger.error(f"Error sending event to XAI: {e}")
    
    async def send_audio(self, audio_data: bytes):
        """
        Send audio data to XAI Realtime API.
        
        Args:
            audio_data: Raw PCM audio bytes (16kHz, 16-bit, mono)
        """
        if not self.websocket or self.websocket.state != WebSocketState.OPEN:
            return
        
        # Encode audio to base64
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
        
        event = {
            "type": "input_audio_buffer.append",
            "audio": audio_base64
        }
        
        await self._send_event(event)
    
    async def commit_audio(self):
        """Signal that audio input is complete."""
        if not self.websocket or self.websocket.state != WebSocketState.OPEN:
            return
        
        # Commit the audio buffer
        await self._send_event({"type": "input_audio_buffer.commit"})
    
    async def _receive_loop(self):
        """Main loop for receiving messages from XAI."""
        try:
            while self._running and self.websocket:
                try:
                    message = await asyncio.wait_for(
                        self.websocket.recv(),
                        timeout=60.0
                    )
                    await self._handle_message(message)
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logger.info("XAI WebSocket connection closed")
                    break
        except asyncio.CancelledError:
            logger.debug("Receive loop cancelled")
        except Exception as e:
            logger.error(f"Error in receive loop: {e}")
        finally:
            self._running = False
    
    async def _handle_message(self, message: str):
        """Handle incoming WebSocket messages from XAI."""
        try:
            event = json.loads(message)
            event_type = event.get("type", "")
            
            if event_type == "error":
                error_details = event.get('error', {})
                logger.error(f"XAI Realtime API error: {error_details}")
                
            elif event_type == "session.created":
                logger.info("XAI Realtime session created")
                
            elif event_type == "session.updated":
                logger.info("⚙️ XAI Realtime session configured successfully")
                
            elif event_type == "response.created":
                logger.info("🤔 Bot is generating a response...")
                self._response_in_progress = True
                
            elif event_type == "response.audio.delta":
                # Received audio chunk from XAI
                audio_base64 = event.get("delta", "")
                if audio_base64:
                    audio_data = base64.b64decode(audio_base64)
                    self._audio_buffer.extend(audio_data)
                    
                    # Send chunks to callback when buffer is large enough
                    while len(self._audio_buffer) >= AUDIO_BUFFER_SIZE:
                        chunk = bytes(self._audio_buffer[:AUDIO_BUFFER_SIZE])
                        del self._audio_buffer[:AUDIO_BUFFER_SIZE]
                        self.on_audio_response(chunk)
                        
            elif event_type == "response.audio.done":
                # Send any remaining audio in buffer
                if self._audio_buffer:
                    self.on_audio_response(bytes(self._audio_buffer))
                    self._audio_buffer.clear()
                logger.info("🔊 Audio response complete")
                
            elif event_type == "response.audio_transcript.delta":
                # Received text transcription of bot's response
                if self.on_text_response:
                    text = event.get("delta", "")
                    if text:
                        self.on_text_response(text)
                        
            elif event_type == "response.audio_transcript.done":
                # Full transcription of bot's response
                transcript = event.get("transcript", "")
                if transcript:
                    logger.info(f"🗣️ Bot said: \"{transcript}\"")
                        
            elif event_type == "conversation.item.input_audio_transcription.completed":
                # User's speech was transcribed
                transcript = event.get("transcript", "")
                if transcript:
                    logger.info(f"📝 User said: \"{transcript}\"")
                    
            elif event_type == "input_audio_buffer.speech_started":
                logger.info("🎤 Speech detected")
                
            elif event_type == "input_audio_buffer.speech_stopped":
                logger.info("🔇 Speech ended")
                # Request a response
                await self._send_event({
                    "type": "response.create",
                    "response": {
                        "modalities": ["text", "audio"]
                    }
                })
                
            elif event_type == "response.done":
                logger.info("✅ Response complete")
                self._response_in_progress = False
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse XAI message: {e}")
        except Exception as e:
            logger.error(f"Error handling XAI message: {e}")
    
    async def disconnect(self):
        """Close the WebSocket connection."""
        self._running = False
        
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None
        
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception as e:
                logger.warning(f"Error closing WebSocket: {e}")
            self.websocket = None
        
        logger.info("Disconnected from XAI Realtime API")


class VoiceConnectionManager:
    """
    Manages voice channel connections and audio streaming for Discord bots.
    Handles the full-duplex speech interaction with XAI's Grok Realtime API.
    """
    
    def __init__(self):
        # Track active voice sessions per guild
        self._sessions: Dict[int, 'VoiceSession'] = {}
        
    def get_session(self, guild_id: int) -> Optional['VoiceSession']:
        """Get the voice session for a guild."""
        return self._sessions.get(guild_id)
    
    def has_active_session(self, guild_id: int) -> bool:
        """Check if a guild has an active voice session."""
        return guild_id in self._sessions
    
    async def connect(self, voice_channel: discord.VoiceChannel, text_channel: Optional[discord.TextChannel] = None) -> tuple[Optional['VoiceSession'], Optional[str]]:
        """
        Connect to a voice channel and start a new voice session.
        
        Args:
            voice_channel: The Discord voice channel to join
            text_channel: Optional text channel to post generated images to
            
        Returns:
            Tuple of (VoiceSession, None) if successful, or (None, error_reason) on failure
        """
        guild_id = voice_channel.guild.id
        
        # Check if already connected
        if guild_id in self._sessions:
            logger.warning(f"Already connected to a voice channel in guild {guild_id}")
            return self._sessions[guild_id], None
        
        try:
            # Connect to voice channel
            logger.info(f"🎙️ Connecting to voice channel '{voice_channel.name}' (ID: {voice_channel.id}) in guild {guild_id}")
            
            # Use VoiceRecvClient if available for voice input support
            if VOICE_RECV_AVAILABLE:
                logger.info("📥 Voice receive extension available - enabling voice input")
                voice_client = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
            else:
                logger.warning("⚠️ Voice receive extension not available - voice input disabled")
                voice_client = await voice_channel.connect()
            
            logger.info(f"✅ Successfully connected to Discord voice channel '{voice_channel.name}'")
            
            # Create voice session with text channel for image posting
            session = VoiceSession(voice_client, self, text_channel)
            self._sessions[guild_id] = session
            
            # Start the session (connects to XAI and starts audio processing)
            logger.info("🚀 Starting voice session and XAI Realtime API connection...")
            success, error_reason = await session.start()
            
            if success:
                logger.info(f"✅ Voice session fully started in guild {guild_id}")
                return session, None
            else:
                # Failed to start session, cleanup
                logger.error(f"❌ Voice session failed to start in guild {guild_id}: {error_reason}")
                await self.disconnect(guild_id)
                return None, error_reason
                
        except discord.ClientException as e:
            error_msg = f"Discord client error: {e}"
            logger.error(f"❌ {error_msg}")
            return None, error_msg
        except discord.opus.OpusNotLoaded as e:
            error_msg = f"Opus library not loaded (required for voice): {e}"
            logger.error(f"❌ {error_msg}")
            return None, error_msg
        except Exception as e:
            error_msg = f"Voice channel connection error: {type(e).__name__}: {e}"
            logger.error(f"❌ {error_msg}")
            return None, error_msg
    
    async def disconnect(self, guild_id: int) -> bool:
        """
        Disconnect from voice channel and cleanup session.
        
        Args:
            guild_id: The Discord guild ID
            
        Returns:
            True if disconnected successfully, False otherwise
        """
        session = self._sessions.pop(guild_id, None)
        if session:
            await session.stop()
            logger.debug(f"[DEBUG] Voice session disconnected for guild {guild_id}")
            return True
        logger.debug(f"[DEBUG] No active session found for guild {guild_id}")
        return False
    
    async def disconnect_all(self):
        """Disconnect from all voice channels."""
        logger.debug(f"[DEBUG] Disconnecting all voice sessions ({len(self._sessions)} active)")
        guild_ids = list(self._sessions.keys())
        for guild_id in guild_ids:
            await self.disconnect(guild_id)


class StreamingAudioSource(discord.AudioSource):
    """Audio source that streams audio from a queue."""
    
    def __init__(self):
        self._audio_queue: deque = deque()
        self._current_chunk: Optional[bytes] = None
        self._chunk_position = 0
        self._frame_size = 3840  # 20ms of audio at 48kHz stereo (960 samples * 2 channels * 2 bytes)
        self._is_playing = False
        
    def add_audio(self, audio_data: bytes):
        """Add audio data to the playback queue."""
        self._audio_queue.append(audio_data)
        self._is_playing = True
        
    def read(self) -> bytes:
        """Read the next frame of audio data."""
        # Try to get more data if needed
        while self._current_chunk is None or self._chunk_position >= len(self._current_chunk):
            if self._audio_queue:
                self._current_chunk = self._audio_queue.popleft()
                self._chunk_position = 0
            else:
                # No more audio, return silence
                self._is_playing = False
                return b'\x00' * self._frame_size
        
        # Extract frame from current chunk
        end_pos = min(self._chunk_position + self._frame_size, len(self._current_chunk))
        frame = self._current_chunk[self._chunk_position:end_pos]
        self._chunk_position = end_pos
        
        # Pad with silence if needed
        if len(frame) < self._frame_size:
            frame += b'\x00' * (self._frame_size - len(frame))
        
        return frame
    
    def is_opus(self) -> bool:
        """Return False since we're providing raw PCM audio."""
        return False
    
    @property
    def is_playing(self) -> bool:
        """Check if audio is currently being played."""
        return self._is_playing or bool(self._audio_queue)
    
    def cleanup(self):
        """Clean up the audio source."""
        self._audio_queue.clear()
        self._current_chunk = None
        self._chunk_position = 0


class XAIVoiceSink(voice_recv.AudioSink if VOICE_RECV_AVAILABLE else object):
    """
    Audio sink that receives voice data from Discord and streams it to XAI.
    Implements the discord-ext-voice-recv AudioSink interface.
    """
    
    # Maximum number of Opus decode errors to log per SSRC before suppressing
    MAX_ERROR_LOGS_PER_SSRC = 3
    
    def __init__(self, voice_session: 'VoiceSession'):
        """
        Initialize the XAI voice sink.
        
        Args:
            voice_session: The VoiceSession instance to send audio to
        """
        self._voice_session = voice_session
        self._loop = asyncio.get_event_loop()
        # Audio buffer for batching chunks to reduce cross-thread calls
        self._audio_buffer = bytearray()
        self._buffer_lock = asyncio.Lock()
        # Buffer threshold: ~100ms of audio at 16kHz mono (1600 samples * 2 bytes)
        self._buffer_threshold = 3200
        # Track known SSRCs to log warnings for unknown sources
        self._known_ssrcs = set()
        # Track Opus decode errors per SSRC to avoid log spam (auto-initialized to 0)
        self._error_count_per_ssrc = defaultdict(int)
        
    def wants_opus(self) -> bool:
        """Return False - we want decoded PCM audio, not Opus."""
        return False
    
    def write(self, user: discord.User, data: 'voice_recv.VoiceData'):
        """
        Handle incoming voice data from a user.
        
        This method is called by discord-ext-voice-recv when audio is received.
        The audio is in Discord format (48kHz, 16-bit, stereo PCM).
        
        Args:
            user: The Discord user who is speaking
            data: The voice data containing PCM audio
        """
        if not self._voice_session.xai_session:
            return
        
        # Track SSRC for monitoring unknown sources
        ssrc = getattr(data, 'ssrc', None)
        if ssrc is not None and ssrc not in self._known_ssrcs:
            self._known_ssrcs.add(ssrc)
            logger.debug(f"New voice source detected - SSRC: {ssrc}, User: {user}")
        
        try:
            # Get the PCM audio data (48kHz, 16-bit, stereo)
            # Note: Accessing data.pcm triggers Opus decoding which may raise OpusError
            # for corrupted streams or packets from unknown SSRCs. OSError can also be
            # raised when the underlying audio data is invalid.
            try:
                pcm_data = data.pcm
            except (OpusError, OSError) as opus_error:
                # Handle Opus decoding errors gracefully without crashing
                # OpusError: corrupted stream, decoder errors
                # OSError: can occur with invalid audio data
                
                # Track errors per SSRC to avoid log spam
                if ssrc is not None:
                    # Increment error count efficiently using defaultdict
                    self._error_count_per_ssrc[ssrc] += 1
                    error_count = self._error_count_per_ssrc[ssrc]
                    
                    # Only log the first few errors per SSRC to avoid spam
                    if error_count <= self.MAX_ERROR_LOGS_PER_SSRC:
                        logger.warning(
                            f"Opus decode error for SSRC {ssrc} (User: {user}): {type(opus_error).__name__}: {opus_error}"
                        )
                    elif error_count == self.MAX_ERROR_LOGS_PER_SSRC + 1:
                        logger.warning(
                            f"Suppressing further Opus errors for SSRC {ssrc} (User: {user})"
                        )
                else:
                    logger.warning(f"Opus decode error (User: {user}): {type(opus_error).__name__}: {opus_error}")
                
                # Skip this packet and continue - don't crash the entire receive loop
                return
            
            if pcm_data:
                # Resample from Discord format (48kHz stereo) to XAI format (16kHz mono)
                # Using the static method directly for efficiency
                resampled_audio = AudioResampler.resample_48k_stereo_to_16k_mono(pcm_data)
                
                if resampled_audio:
                    # Add to buffer
                    self._audio_buffer.extend(resampled_audio)
                    
                    # Send when buffer reaches threshold to reduce cross-thread calls
                    if len(self._audio_buffer) >= self._buffer_threshold:
                        audio_to_send = bytes(self._audio_buffer)
                        self._audio_buffer.clear()
                        
                        # Schedule the async send_audio call in the event loop
                        asyncio.run_coroutine_threadsafe(
                            self._voice_session.xai_session.send_audio(audio_to_send),
                            self._loop
                        )
        except Exception as e:
            # Catch any other unexpected errors
            logger.error(f"Unexpected error processing voice data from {user}: {type(e).__name__}: {e}")
    
    def cleanup(self):
        """Clean up the audio sink and flush any remaining audio."""
        # Flush any remaining buffered audio
        if self._audio_buffer and self._voice_session.xai_session:
            try:
                audio_to_send = bytes(self._audio_buffer)
                self._audio_buffer.clear()
                asyncio.run_coroutine_threadsafe(
                    self._voice_session.xai_session.send_audio(audio_to_send),
                    self._loop
                )
            except Exception as e:
                logger.warning(f"Error flushing audio buffer during cleanup: {e}")



class VoiceSession:
    """
    Represents an active voice chat session with XAI Realtime API.
    Handles receiving audio from Discord and sending responses back.
    """
    
    def __init__(self, voice_client: VoiceClient, manager: VoiceConnectionManager, text_channel: Optional[discord.TextChannel] = None):
        self.voice_client = voice_client
        self.manager = manager
        self.text_channel = text_channel  # Channel to post generated images to
        self.xai_session: Optional[XAIRealtimeSession] = None
        self._running = False
        self._audio_source: Optional[StreamingAudioSource] = None
        self._audio_sink: Optional['XAIVoiceSink'] = None
        self._listen_task: Optional[asyncio.Task] = None
        
    @property
    def guild_id(self) -> int:
        """Get the guild ID for this session."""
        return self.voice_client.guild.id
    
    @property
    def channel(self) -> discord.VoiceChannel:
        """Get the voice channel for this session."""
        return self.voice_client.channel
        
    async def start(self) -> tuple[bool, Optional[str]]:
        """
        Start the voice session.
        Connects to XAI and begins audio processing.
        
        Returns:
            Tuple of (True, None) if started successfully, or (False, error_reason) on failure
        """
        # Create audio source for playback
        self._audio_source = StreamingAudioSource()
        
        # Create XAI session with callback for audio responses
        self.xai_session = XAIRealtimeSession(
            on_audio_response=self._handle_xai_audio
        )
        
        # Connect to XAI
        logger.info("🔗 Connecting to XAI Realtime API...")
        success, error_reason = await self.xai_session.connect()
        
        if not success:
            logger.error(f"❌ Failed to connect to XAI Realtime API: {error_reason}")
            return False, error_reason
        
        logger.info("✅ Successfully connected to XAI Realtime API")
        self._running = True
        
        # Start listening for Discord audio
        self._listen_task = asyncio.create_task(self._listen_loop())
        
        # Start playing audio source
        try:
            self.voice_client.play(self._audio_source)
            logger.info("🔊 Audio playback initialized")
        except Exception as e:
            error_msg = f"Audio playback error: {type(e).__name__}: {e}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg
        
        return True, None
    
    def _handle_xai_audio(self, audio_data: bytes):
        """
        Handle audio data received from XAI.
        Resamples and queues for playback.
        
        Args:
            audio_data: Raw PCM audio (16kHz, 16-bit, mono)
        """
        # Resample to Discord format (48kHz stereo) using static method
        discord_audio = AudioResampler.resample_16k_mono_to_48k_stereo(audio_data)
        
        # Add to playback queue
        if self._audio_source:
            self._audio_source.add_audio(discord_audio)
    
    async def _listen_loop(self):
        """
        Main loop for receiving audio from Discord voice channel.
        
        Uses discord-ext-voice-recv extension when available to capture voice input
        and stream it to XAI Realtime API.
        """
        try:
            logger.info("🎧 Voice session active - connected to XAI Realtime API")
            
            # Check if voice receive is available and voice client supports it
            if VOICE_RECV_AVAILABLE and isinstance(self.voice_client, voice_recv.VoiceRecvClient):
                logger.info("✅ Voice INPUT enabled - bot can listen and respond")
                
                # Create and start the audio sink for receiving voice
                self._audio_sink = XAIVoiceSink(self)
                self.voice_client.listen(self._audio_sink)
                logger.info("🎤 Now listening for voice input from users")
                
                # Keep the session alive while listening
                while self._running:
                    await asyncio.sleep(0.1)
                    
            else:
                # Voice receive not available - playback only mode
                if not VOICE_RECV_AVAILABLE:
                    logger.warning("⚠️ Voice INPUT is not available - discord-ext-voice-recv not installed")
                    logger.info("📋 To enable voice input: pip install discord-ext-voice-recv")
                else:
                    logger.warning("⚠️ Voice INPUT is not available - VoiceRecvClient not active")
                
                logger.info("🔊 Bot can only PLAY audio responses, not LISTEN to users")
                
                # Keep the session alive in playback-only mode
                while self._running:
                    await asyncio.sleep(0.1)
                
        except asyncio.CancelledError:
            logger.debug("Listen loop cancelled")
        except Exception as e:
            logger.error(f"Error in listen loop: {e}")
        finally:
            logger.debug("Listen loop ended")
    
    async def stop(self):
        """Stop the voice session and cleanup."""
        logger.info(f"🔌 Stopping voice session in guild {self.guild_id}...")
        self._running = False
        
        # Stop listening for voice input if active
        if VOICE_RECV_AVAILABLE and isinstance(self.voice_client, voice_recv.VoiceRecvClient):
            try:
                self.voice_client.stop_listening()
                logger.info("🔇 Stopped listening for voice input")
            except Exception as e:
                logger.warning(f"Error stopping voice listening: {e}")
        
        # Cleanup audio sink
        if self._audio_sink:
            self._audio_sink.cleanup()
            self._audio_sink = None
        
        # Cancel listen task
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None
        
        # Disconnect from XAI
        if self.xai_session:
            logger.info("🔗 Disconnecting from XAI Realtime API...")
            await self.xai_session.disconnect()
            self.xai_session = None
        
        # Stop audio playback
        if self.voice_client.is_playing():
            self.voice_client.stop()
        
        # Cleanup audio source
        if self._audio_source:
            self._audio_source.cleanup()
            self._audio_source = None
        
        # Disconnect from voice channel
        if self.voice_client.is_connected():
            await self.voice_client.disconnect()
        
        logger.info(f"👋 Voice session stopped in guild {self.guild_id}")


# Global voice connection manager instance
voice_manager = VoiceConnectionManager()

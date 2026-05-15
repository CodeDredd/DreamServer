// useVoiceAgent — kapselt die LiveKit-WebRTC-Verbindung fuer die Voice-
// Page (Phase 4 Welle C.2). Pendant zu dashboard/src/hooks/useVoiceAgent.js.
//
// LiveKit-Client ist eine *optionale* Runtime-Dependency: weder das
// React-Original noch die Nuxt-Variante listen ihn in package.json —
// er wird per dynamic `import('livekit-client')` geladen, sobald der
// Nutzer das Mikrofon-Button drueckt. Falls nicht installiert, faengt
// der try/catch den Fehler und zeigt ihn im Error-Banner.
//
// Komponenten-lokales State, kein Module-Cache: jede Voice-Page-
// Instanz haelt ihre eigene Verbindung. (LiveKit-Rooms sind nicht
// teilbar.)

import { onBeforeUnmount, ref, type Ref } from 'vue'
import { useApi } from '~/composables/useApi'

export type VoiceStatus = 'disconnected' | 'connecting' | 'connected' | 'error'

export interface VoiceMessage {
  role: 'user' | 'assistant' | string
  content: string
  timestamp: number
}

function livekitUrl(): string {
  if (typeof window === 'undefined') return 'ws://localhost:7880'
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.hostname}:7880`
}

export function useVoiceAgent() {
  const api = useApi()

  const status: Ref<VoiceStatus> = ref('disconnected')
  const isListening = ref(false)
  const isSpeaking = ref(false)
  const messages: Ref<VoiceMessage[]> = ref([])
  const currentTranscript = ref('')
  const error: Ref<string | null> = ref(null)
  const volume = ref(1.0)
  const isMuted = ref(false)

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let room: any = null
  let mediaStream: MediaStream | null = null
  let activeAudioElement: HTMLAudioElement | null = null
  const allAudioElements: HTMLAudioElement[] = []

  async function getToken(): Promise<string> {
    const data = await api.post<{ token: string }>('/api/voice/token', {
      identity: `dashboard-${Date.now()}`,
    })
    return data.token
  }

  async function connect() {
    try {
      status.value = 'connecting'
      error.value = null

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let livekit: any
      try {
        // @ts-expect-error — optional runtime dependency
        livekit = await import('livekit-client')
      }
      catch {
        throw new Error(
          'livekit-client is not installed. Run "pnpm add livekit-client" in the dashboard-nuxt service.',
        )
      }
      const { Room, RoomEvent, Track, createLocalAudioTrack } = livekit

      const token = await getToken()

      room = new Room({ adaptiveStream: true, dynacast: true })

      room.on(RoomEvent.Connected, () => { status.value = 'connected' })
      room.on(RoomEvent.Disconnected, () => {
        status.value = 'disconnected'
        isListening.value = false
      })

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      room.on(RoomEvent.TrackSubscribed, (track: any) => {
        if (track.kind === Track.Kind.Audio) {
          const el = track.attach() as HTMLAudioElement
          el.volume = volume.value
          el.muted = isMuted.value
          document.body.appendChild(el)
          activeAudioElement = el
          allAudioElements.push(el)
          isSpeaking.value = true
        }
      })

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      room.on(RoomEvent.TrackUnsubscribed, (track: any) => {
        if (track.kind === Track.Kind.Audio) {
          track.detach()
          isSpeaking.value = false
        }
      })

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      room.on(RoomEvent.DataReceived, (data: Uint8Array) => {
        try {
          const msg = JSON.parse(new TextDecoder().decode(data)) as {
            type: string
            text?: string
            role?: string
            final?: boolean
          }
          if (msg.type === 'transcript') {
            if (msg.final) {
              messages.value = [
                ...messages.value,
                {
                  role: msg.role || 'user',
                  content: msg.text ?? '',
                  timestamp: Date.now(),
                },
              ]
              currentTranscript.value = ''
            }
            else {
              currentTranscript.value = msg.text ?? ''
            }
          }
          else if (msg.type === 'assistant_speaking') isSpeaking.value = true
          else if (msg.type === 'assistant_done') isSpeaking.value = false
        }
        catch (err) {
          // eslint-disable-next-line no-console
          console.error('voice: failed to parse data message', err)
        }
      })

      await room.connect(livekitUrl(), token)

      const audioTrack = await createLocalAudioTrack({
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      })
      await room.localParticipant.publishTrack(audioTrack)
      mediaStream = audioTrack.mediaStream
    }
    catch (err: unknown) {
      // eslint-disable-next-line no-console
      console.error('voice: connection error', err)
      error.value = (err as Error).message || 'Voice connection failed'
      status.value = 'error'
    }
  }

  async function disconnect() {
    if (room) {
      try { await room.disconnect() } catch { /* ignore */ }
      room = null
    }
    if (mediaStream) {
      mediaStream.getTracks().forEach(t => t.stop())
      mediaStream = null
    }
    for (const el of allAudioElements) {
      el.parentNode?.removeChild(el)
    }
    allAudioElements.length = 0
    activeAudioElement = null
    status.value = 'disconnected'
    isListening.value = false
  }

  async function toggleListening() {
    if (!room) {
      await connect()
      isListening.value = true
      return
    }
    const next = !isListening.value
    isListening.value = next
    const pubs = room.localParticipant.getTrackPublications()
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    for (const pub of pubs.values() as Iterable<any>) {
      if (pub.track?.kind === 'audio') {
        if (next) await pub.track.unmute()
        else await pub.track.mute()
      }
    }
  }

  function toggleMute() {
    isMuted.value = !isMuted.value
    if (activeAudioElement) activeAudioElement.muted = isMuted.value
  }

  function updateVolume(v: number) {
    volume.value = v
    if (activeAudioElement) activeAudioElement.volume = v
  }

  function interrupt() {
    if (room) {
      const enc = new TextEncoder()
      void room.localParticipant.publishData(
        enc.encode(JSON.stringify({ type: 'interrupt' })),
        { reliable: true },
      )
    }
    isSpeaking.value = false
  }

  function clearMessages() {
    messages.value = []
  }

  onBeforeUnmount(() => { void disconnect() })

  return {
    status,
    isListening,
    isSpeaking,
    messages,
    currentTranscript,
    error,
    volume,
    isMuted,
    connect,
    disconnect,
    toggleListening,
    toggleMute,
    updateVolume,
    interrupt,
    clearMessages,
  }
}


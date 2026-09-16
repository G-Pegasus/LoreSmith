import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RotateCcw, Send, Sparkles } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { confirmInspirationSettings, fetchInspirationSession, streamInspirationMessage } from '../../lib/api/inspiration'
import type { InspirationMessage, InspirationSession, InspirationSettings } from '../../lib/types/api'
import { SettingConfirmSheet, countSettingsSlots } from './SettingConfirmSheet'

type InspirationChatPanelProps = {
  sessionId: string
  /** 用户确认整张设定单后，把快照交给上层铺进右侧表单 */
  onConfirmed?: (settings: InspirationSettings) => void
  /** 用户确认重置：上层负责轮换 sessionId 并重挂载，本组件只负责发出信号 */
  onReset?: () => void
}

type ConfirmedCard = {
  messageId: string
  revision: number
  settings: InspirationSettings
}

const starterPrompts = [
  '我想写一个现代都市悬疑爱情故事，女主能听见别人未说出口的遗憾。',
  '帮我把“废土修仙”和“家族复仇”结合成一个能写长篇的设定。',
  '我只有主角是反派养大的天才少女这个想法，帮我扩成前三章大纲。',
]

export function InspirationChatPanel({ sessionId, onConfirmed, onReset }: InspirationChatPanelProps) {
  const [draft, setDraft] = useState('')
  const [streamingUser, setStreamingUser] = useState<InspirationMessage | null>(null)
  const [streamingAssistant, setStreamingAssistant] = useState('')
  const [streamPhase, setStreamPhase] = useState('')
  const [streamError, setStreamError] = useState('')
  const [confirmedCard, setConfirmedCard] = useState<ConfirmedCard | null>(null)
  const [confirmingReset, setConfirmingReset] = useState(false)
  const threadRef = useRef<HTMLDivElement | null>(null)
  const streamBufferRef = useRef('')
  const streamFlushRef = useRef<number | null>(null)
  const queryClient = useQueryClient()
  const sessionQuery = useQuery({
    queryKey: ['inspiration-session', sessionId],
    queryFn: () => fetchInspirationSession(sessionId),
    enabled: Boolean(sessionId),
  })
  const sendMutation = useMutation({
    mutationFn: (content: string) => {
      if (streamFlushRef.current !== null) {
        window.clearTimeout(streamFlushRef.current)
        streamFlushRef.current = null
      }
      streamBufferRef.current = ''
      const optimisticUser: InspirationMessage = {
        messageId: `local_${crypto.randomUUID()}`,
        role: 'user',
        content,
        createdAt: new Date().toISOString(),
      }
      setStreamingUser(optimisticUser)
      setStreamingAssistant('')
      setStreamPhase('')
      setStreamError('')
      return streamInspirationMessage(sessionId, content, {
        onUser: setStreamingUser,
        onPhase: setStreamPhase,
        onDelta: (delta) => {
          streamBufferRef.current += delta
          if (streamFlushRef.current !== null) return
          streamFlushRef.current = window.setTimeout(() => {
            setStreamingAssistant((current) => current + streamBufferRef.current)
            streamBufferRef.current = ''
            streamFlushRef.current = null
          }, 16)
        },
      })
    },
    onSuccess: (session) => {
      if (streamFlushRef.current !== null) {
        window.clearTimeout(streamFlushRef.current)
        streamFlushRef.current = null
      }
      if (streamBufferRef.current) {
        setStreamingAssistant((current) => current + streamBufferRef.current)
        streamBufferRef.current = ''
      }
      queryClient.setQueryData(['inspiration-session', sessionId], session)
      setStreamingUser(null)
      setStreamingAssistant('')
      setStreamPhase('')
    },
    onError: (error) => {
      setStreamPhase('')
      setStreamError(error instanceof Error ? error.message : '灵感对话暂时不可用，请稍后重试。')
    },
  })
  const confirmMutation = useMutation({
    mutationFn: (payload: ConfirmedCard) => confirmInspirationSettings(sessionId, payload.revision),
    onSuccess: (session: InspirationSession, payload: ConfirmedCard) => {
      queryClient.setQueryData(['inspiration-session', sessionId], session)
      setConfirmedCard(payload)
      setStreamError('')
      onConfirmed?.(payload.settings)
    },
    onError: (error) => {
      setStreamError(error instanceof Error ? error.message : '设定确认失败，请重试。')
    },
  })

  const session = sessionQuery.data
  const messages = session?.messages ?? []
  const displayedMessages = [
    ...messages,
    ...(streamingUser ? [streamingUser] : []),
    ...(sendMutation.isPending
      ? [
          {
            messageId: 'streaming_assistant',
            role: 'assistant' as const,
            content: streamingAssistant || '正在回应…',
            createdAt: new Date().toISOString(),
          },
        ]
      : []),
  ]
  const hasMessages = displayedMessages.length > 0
  const canSend = draft.trim().length > 0 && !sendMutation.isPending

  const draftSettings = session?.draft ?? null
  const draftRevision = session?.draftRevision ?? 0
  const confirmedRevision = session?.confirmedRevision ?? 0
  const draftSourceMessageId = session?.draftSourceMessageId ?? null
  const slotCount = countSettingsSlots(draftSettings)
  // 服务端确认后会把指针清空，所以「已确认」卡片靠本地记住它原本挂在哪条消息下。
  const showSheet = Boolean(draftSettings) && draftRevision > confirmedRevision
  // 对话或确认进行中：重置按钮禁用（在途 SSE 没有 AbortController，撤不回来），确认单同样锁住
  const busy = sendMutation.isPending || confirmMutation.isPending
  const sheetLocked = busy
  const settingsLabel = `设定 ${slotCount} / 4 项${draftRevision > confirmedRevision ? ' · 有更新' : ''}`

  useEffect(() => {
    const thread = threadRef.current
    if (!thread) return
    thread.scrollTo({ top: thread.scrollHeight, behavior: 'smooth' })
  }, [displayedMessages.length, streamingAssistant, streamPhase])

  useEffect(() => {
    return () => {
      if (streamFlushRef.current !== null) {
        window.clearTimeout(streamFlushRef.current)
      }
    }
  }, [])

  const submit = async (content: string) => {
    const text = content.trim()
    if (!text) return
    setDraft('')
    try {
      await sendMutation.mutateAsync(text)
    } catch {
      // Error state is rendered from the mutation; keep the composer usable.
    }
  }

  const confirmSheet = (payload: ConfirmedCard) => {
    confirmMutation.mutate(payload)
  }

  return (
    <section className='inspiration-panel panel'>
      <div className='inspiration-panel__header'>
        <div>
          <div className='workspace-sidebar__eyebrow'>灵感对话</div>
          <h2>和 AI 打磨设定</h2>
        </div>
        <div className='inspiration-panel__header-actions'>
          <span className='status-badge inspiration-panel__memory'>{settingsLabel}</span>
          <button
            className='inspiration-panel__reset'
            type='button'
            title='重置对话'
            aria-label='重置对话'
            disabled={busy}
            onClick={() => setConfirmingReset(true)}
          >
            <RotateCcw size={15} />
          </button>
        </div>
      </div>

      {confirmingReset ? (
        <div className='inspiration-panel__reset-confirm' role='alertdialog' aria-label='确认重置对话'>
          <p>重置会清空当前对话、设定单和右侧已填内容，且无法恢复。</p>
          <div className='inspiration-panel__reset-actions'>
            <button
              className='secondary-button secondary-button--small'
              type='button'
              onClick={() => setConfirmingReset(false)}
            >
              取消
            </button>
            <button
              className='primary-button inspiration-panel__reset-submit'
              type='button'
              onClick={() => {
                setConfirmingReset(false)
                onReset?.()
              }}
            >
              确认重置
            </button>
          </div>
        </div>
      ) : null}

      <div className='inspiration-panel__body'>
        {!hasMessages ? (
          <div className='inspiration-empty'>
            <Sparkles size={24} />
            <strong>从一个模糊想法开始</strong>
            <p>输入你的题材、人物、世界观碎片或想要的读者情绪，AI 会围绕标题、世界观、角色、故事简介四项帮你把它们敲定。</p>
            <div className='inspiration-starters'>
              {starterPrompts.map((prompt) => (
                <button key={prompt} type='button' onClick={() => setDraft(prompt)}>
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className='inspiration-thread' ref={threadRef}>
            {displayedMessages.map((message) => (
              <div key={message.messageId}>
                <article className={`inspiration-message inspiration-message--${message.role}`}>
                  <div className='inspiration-message__role'>{message.role === 'assistant' ? 'AI 灵感顾问' : '你'}</div>
                  {message.role === 'assistant' ? (
                    <div className='inspiration-message__content inspiration-message__markdown'>
                      <ReactMarkdown>{message.content}</ReactMarkdown>
                    </div>
                  ) : (
                    <div className='inspiration-message__content'>{message.content}</div>
                  )}
                </article>
                {showSheet && draftSettings && message.messageId === draftSourceMessageId ? (
                  <SettingConfirmSheet
                    settings={draftSettings}
                    revision={draftRevision}
                    confirmedSettings={session?.confirmedSettings ?? null}
                    locked={sheetLocked}
                    confirmed={false}
                    submitting={confirmMutation.isPending}
                    onConfirm={() =>
                      confirmSheet({
                        messageId: message.messageId,
                        revision: draftRevision,
                        settings: draftSettings,
                      })
                    }
                  />
                ) : null}
                {confirmedCard && message.messageId === confirmedCard.messageId ? (
                  <SettingConfirmSheet
                    settings={confirmedCard.settings}
                    revision={confirmedCard.revision}
                    confirmedSettings={confirmedCard.settings}
                    locked
                    confirmed
                    submitting={false}
                    onConfirm={() => undefined}
                  />
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className='inspiration-composer'>
        <textarea
          className='textarea inspiration-composer__input'
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder='描述你的作品设定、角色关系、想要的题材或卡住的问题...'
          disabled={sendMutation.isPending}
        />
        <button className='assistant-panel__send inspiration-composer__send' type='button' disabled={!canSend} onClick={() => void submit(draft)}>
          <Send size={18} />
        </button>
      </div>

      {streamPhase === 'extracting' ? <div className='inspiration-composer__phase'>正在整理设定…</div> : null}

      {sessionQuery.isError || sendMutation.isError || confirmMutation.isError ? (
        <div className='assistant-panel__error'>{streamError || '灵感对话暂时不可用，请确认 Java 服务和数据库已启动。'}</div>
      ) : null}
    </section>
  )
}

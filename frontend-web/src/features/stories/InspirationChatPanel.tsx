import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Send, Sparkles } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { fetchInspirationSession, streamInspirationMessage } from '../../lib/api/inspiration'
import type { InspirationMessage } from '../../lib/types/api'

type InspirationChatPanelProps = {
  sessionId: string
}

const starterPrompts = [
  '我想写一个现代都市悬疑爱情故事，女主能听见别人未说出口的遗憾。',
  '帮我把“废土修仙”和“家族复仇”结合成一个能写长篇的设定。',
  '我只有主角是反派养大的天才少女这个想法，帮我扩成前三章大纲。',
]

export function InspirationChatPanel({ sessionId }: InspirationChatPanelProps) {
  const [draft, setDraft] = useState('')
  const [streamingUser, setStreamingUser] = useState<InspirationMessage | null>(null)
  const [streamingAssistant, setStreamingAssistant] = useState('')
  const [streamError, setStreamError] = useState('')
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
      setStreamError('')
      return streamInspirationMessage(sessionId, content, {
        onUser: setStreamingUser,
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
    },
    onError: (error) => {
      setStreamError(error instanceof Error ? error.message : '灵感对话暂时不可用，请稍后重试。')
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
            content: streamingAssistant || '正在整理设定、冲突和大纲建议...',
            createdAt: new Date().toISOString(),
          },
        ]
      : []),
  ]
  const hasMessages = displayedMessages.length > 0
  const canSend = draft.trim().length > 0 && !sendMutation.isPending
  const memoryLabel = useMemo(() => {
    const memory = session?.memorySummary?.trim() ?? ''
    if (!memory) return '记忆未建立'
    return `已记忆 ${Math.min(memory.length, 9999)} 字`
  }, [session?.memorySummary])

  useEffect(() => {
    const thread = threadRef.current
    if (!thread) return
    thread.scrollTo({ top: thread.scrollHeight, behavior: 'smooth' })
  }, [displayedMessages.length, streamingAssistant])

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

  return (
    <section className='inspiration-panel panel'>
      <div className='inspiration-panel__header'>
        <div>
          <div className='workspace-sidebar__eyebrow'>灵感对话</div>
          <h2>和 AI 打磨设定</h2>
        </div>
        <span className='status-badge inspiration-panel__memory'>{memoryLabel}</span>
      </div>

      <div className='inspiration-panel__body'>
        {!hasMessages ? (
          <div className='inspiration-empty'>
            <Sparkles size={24} />
            <strong>从一个模糊想法开始</strong>
            <p>输入你的题材、人物、世界观碎片或想要的读者情绪，AI 会帮你拓展设定、整理矛盾，并给出大纲建议。</p>
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
              <article key={message.messageId} className={`inspiration-message inspiration-message--${message.role}`}>
                <div className='inspiration-message__role'>{message.role === 'assistant' ? 'AI 灵感顾问' : '你'}</div>
                {message.role === 'assistant' ? (
                  <div className='inspiration-message__content inspiration-message__markdown'>
                    <ReactMarkdown>{message.content}</ReactMarkdown>
                  </div>
                ) : (
                  <div className='inspiration-message__content'>{message.content}</div>
                )}
              </article>
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

      {sessionQuery.isError || sendMutation.isError ? (
        <div className='assistant-panel__error'>{streamError || '灵感对话暂时不可用，请确认 Java 服务和数据库已启动。'}</div>
      ) : null}
    </section>
  )
}

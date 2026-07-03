import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { BookOpen, PenLine, Send, Settings, Sparkles } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { useNavigate } from 'react-router-dom'
import type { StoryWorkspace } from '../../lib/types/api'

type WorkspaceAssistantPanelProps = {
  workspace: StoryWorkspace
  selectedNodeId: string | null
  isPending: boolean
  streamingText?: string
  onSubmit: (instruction: string) => Promise<void>
}

export function WorkspaceAssistantPanel({
  workspace,
  selectedNodeId,
  isPending,
  streamingText = '',
  onSubmit,
}: WorkspaceAssistantPanelProps) {
  const [instruction, setInstruction] = useState('')
  const [assistantMode, setAssistantMode] = useState<'chat' | 'continue' | 'polish'>('chat')
  const threadRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const navigate = useNavigate()

  const displayedMessages = useMemo(
    () => [
      ...workspace.assistantThread,
      ...(streamingText
        ? [
            {
              id: 'streaming-assistant',
              role: 'assistant' as const,
              content: streamingText,
              createdAt: new Date().toISOString(),
            },
          ]
        : []),
    ],
    [streamingText, workspace.assistantThread],
  )

  const inputPlaceholder = selectedNodeId
    ? assistantMode === 'continue'
      ? '和 AI 讨论下一段怎么写...'
      : assistantMode === 'polish'
        ? '让 AI 润色当前章节片段...'
        : '和 AI 讨论当前章节...'
    : '和 AI 讨论这部作品...'

  useEffect(() => {
    const thread = threadRef.current
    if (!thread) return
    thread.scrollTo({ top: thread.scrollHeight, behavior: 'smooth' })
  }, [displayedMessages.length, streamingText])

  useLayoutEffect(() => {
    const input = inputRef.current
    if (!input) return
    input.style.height = '42px'
    input.style.height = `${Math.min(Math.max(input.scrollHeight, 42), 112)}px`
  }, [instruction])

  const submit = async () => {
    const text = instruction.trim()
    if (!text || isPending) return
    setInstruction('')
    await onSubmit(text)
  }

  return (
    <aside className='workspace-assistant panel'>
      <div className='assistant-panel__header'>
        <h2>AI 创作助手</h2>
        <button type='button' className='workspace-assistant__header-button' aria-label='打开资料页' onClick={() => navigate(`/stories/${workspace.storyId}/reference`)}>
          <Settings size={16} />
        </button>
      </div>

      <div className='workspace-assistant__segments' aria-label='助手模式'>
        <button type='button' className={assistantMode === 'chat' ? 'is-active' : ''} onClick={() => setAssistantMode('chat')}>
          <Sparkles size={14} />
          <span>灵感对话</span>
        </button>
        <button type='button' className={assistantMode === 'continue' ? 'is-active' : ''} onClick={() => setAssistantMode('continue')}>
          <BookOpen size={14} />
          <span>续写助手</span>
        </button>
        <button type='button' className={assistantMode === 'polish' ? 'is-active' : ''} onClick={() => setAssistantMode('polish')}>
          <PenLine size={14} />
          <span>文笔润色</span>
        </button>
      </div>

      <div className='workspace-assistant__thread' ref={threadRef}>
        {displayedMessages.length === 0 ? (
          <div className='workspace-assistant__empty'>
            <strong>暂无对话</strong>
            <p>可以直接询问设定、节奏、人物动机或下一章写法。</p>
          </div>
        ) : null}
        {displayedMessages.map((message) => (
          <div key={message.id} className={`workspace-message workspace-message--${message.role}`}>
            <div className='workspace-message__role'>{message.role === 'assistant' ? 'AI' : message.role === 'user' ? '你' : '系统'}</div>
            {message.role === 'assistant' ? (
              <div className='workspace-message__content workspace-message__markdown'>
                <ReactMarkdown>{message.content}</ReactMarkdown>
              </div>
            ) : (
              <div className='workspace-message__content'>{message.content}</div>
            )}
          </div>
        ))}
      </div>

      <div className='assistant-panel__composer'>
        <textarea
          ref={inputRef}
          className='textarea assistant-panel__input workspace-assistant__input'
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder={inputPlaceholder}
          disabled={isPending}
        />
        <button
          className='assistant-panel__send'
          type='button'
          disabled={!instruction.trim() || isPending}
          onClick={() => void submit()}
        >
          <Send size={18} />
        </button>
      </div>
    </aside>
  )
}

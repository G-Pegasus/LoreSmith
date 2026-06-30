import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Send } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { useNavigate } from 'react-router-dom'
import type { AwaitingConfirmation, StoryWorkspace } from '../../lib/types/api'

type WorkspaceAssistantPanelProps = {
  workspace: StoryWorkspace
  selectedNodeId: string | null
  isPending: boolean
  streamingText?: string
  awaitingConfirmation?: AwaitingConfirmation | null
  onSubmit: (instruction: string) => Promise<void>
  onContinueRun: () => Promise<void>
  runStatus?: string | null
  isContinuingRun?: boolean
}

function WorkspaceStatusSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className='workspace-status-section'>
      <div className='workspace-reference-section__header'>
        <strong>{title}</strong>
      </div>
      <div className='workspace-sidecard workspace-sidecard--reference'>{children}</div>
    </section>
  )
}

export function WorkspaceAssistantPanel({
  workspace,
  selectedNodeId,
  isPending,
  streamingText = '',
  awaitingConfirmation,
  onSubmit,
  onContinueRun,
  runStatus,
  isContinuingRun = false,
}: WorkspaceAssistantPanelProps) {
  const [instruction, setInstruction] = useState('')
  const threadRef = useRef<HTMLDivElement | null>(null)
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

  const canContinueRun = Boolean(
    workspace.runBridge?.activeRunId && (awaitingConfirmation || runStatus === 'waiting_input' || runStatus === 'idle' || runStatus === 'failed' || runStatus === 'canceled'),
  )

  useEffect(() => {
    const thread = threadRef.current
    if (!thread) return
    thread.scrollTo({ top: thread.scrollHeight, behavior: 'smooth' })
  }, [displayedMessages.length, streamingText])

  const submit = async () => {
    const text = instruction.trim()
    if (!text || isPending) return
    setInstruction('')
    await onSubmit(text)
  }

  return (
    <aside className='workspace-assistant panel'>
      <div className='assistant-panel__header'>
        <h2>AI 助手</h2>
        <button type='button' className='secondary-button secondary-button--small' onClick={() => navigate(`/stories/${workspace.storyId}/reference`)}>
          资料页
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
          className='textarea assistant-panel__input workspace-assistant__input'
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder={selectedNodeId ? '和 AI 讨论当前章节...' : '和 AI 讨论这部作品...'}
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

      <div className='workspace-panel-list workspace-panel-list--status'>
        <WorkspaceStatusSection title='运行状态'>
          <p>{isContinuingRun ? '继续写作请求已发出，正在等待新的流式输出。' : runStatus ? `当前状态：${runStatus}` : '当前暂无运行状态。'}</p>
          <button type='button' className='primary-button primary-button--small workspace-reference-entry' disabled={isPending || !canContinueRun} onClick={() => void onContinueRun()}>
            {runStatus === 'failed' || runStatus === 'canceled' ? '重新编写' : '继续编写'}
          </button>
        </WorkspaceStatusSection>

        {awaitingConfirmation ? (
          <WorkspaceStatusSection title='等待继续编写'>
            <strong>已写到第 {awaitingConfirmation.pauseAfterChapter} 章</strong>
            <p>当前已完成 {awaitingConfirmation.completedCount} 章，确认后将从第 {awaitingConfirmation.nextChapter} 章继续生成。</p>
          </WorkspaceStatusSection>
        ) : null}
      </div>
    </aside>
  )
}

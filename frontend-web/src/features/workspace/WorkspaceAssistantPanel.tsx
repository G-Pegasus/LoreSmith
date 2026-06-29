import { useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import type { AwaitingConfirmation, StoryWorkspace } from '../../lib/types/api'

type WorkspaceAssistantPanelProps = {
  mode: 'run' | 'workspace'
  workspace: StoryWorkspace
  selectedNodeId: string | null
  isPending: boolean
  streamingText?: string
  streamingRunText?: string
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
  mode,
  workspace,
  selectedNodeId,
  isPending,
  streamingText = '',
  streamingRunText = '',
  awaitingConfirmation,
  onSubmit,
  onContinueRun,
  runStatus,
  isContinuingRun = false,
}: WorkspaceAssistantPanelProps) {
  const [instruction, setInstruction] = useState('')
  const navigate = useNavigate()

  const latestAssistant = useMemo(() => {
    if (streamingText.trim()) {
      return streamingText
    }
    return [...workspace.assistantThread].reverse().find((message) => message.role === 'assistant')?.content ?? ''
  }, [streamingText, workspace.assistantThread])

  const canContinueRun = Boolean(
    workspace.runBridge?.activeRunId && (awaitingConfirmation || runStatus === 'idle' || runStatus === 'failed' || runStatus === 'canceled'),
  )

  return (
    <aside className='workspace-assistant panel'>
      <div className='assistant-panel__header'>
        <h2>AI 助手</h2>
        <button type='button' className='secondary-button secondary-button--small' onClick={() => navigate(`/stories/${workspace.storyId}/reference`)}>
          资料页
        </button>
      </div>

      <div className='workspace-assistant__notice'>
        {mode === 'workspace' ? '针对当前章节提出修改要求，AI 会直接改写中间正文。' : 'Run 模式下此区域展示生成过程，不会直接写入当前编辑区。'}
      </div>

      <div className='workspace-assistant__thread'>
        {workspace.assistantThread.map((message) => (
          <div key={message.id} className={`workspace-message workspace-message--${message.role}`}>
            <div className='workspace-message__role'>{message.role === 'assistant' ? 'AI' : message.role === 'user' ? '你' : '系统'}</div>
            <div className='workspace-message__content'>{message.content}</div>
          </div>
        ))}
        {streamingText ? (
          <div className='workspace-message workspace-message--assistant'>
            <div className='workspace-message__role'>AI</div>
            <div className='workspace-message__content'>{latestAssistant}</div>
          </div>
        ) : null}
        {mode === 'run' && streamingRunText ? (
          <div className='workspace-message workspace-message--assistant'>
            <div className='workspace-message__role'>生成中</div>
            <div className='workspace-message__content'>{streamingRunText}</div>
          </div>
        ) : null}
      </div>

      <div className='assistant-panel__composer'>
        <input
          className='input assistant-panel__input'
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder='例如：压缩开头节奏并强化人物心理'
          disabled={mode !== 'workspace' || isPending || !selectedNodeId}
        />
        <button
          className='assistant-panel__send'
          type='button'
          disabled={mode !== 'workspace' || isPending || !selectedNodeId}
          onClick={async () => {
            await onSubmit(instruction)
            setInstruction('')
          }}
        >
          ✦
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

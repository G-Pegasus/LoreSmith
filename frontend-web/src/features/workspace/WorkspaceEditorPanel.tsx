import { useLayoutEffect, useMemo, useRef } from 'react'
import { Bold, FileText, Globe2, Italic, List, MoreHorizontal } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { StoryWorkspace, WorkspaceNode } from '../../lib/types/api'

type WorkspaceEditorPanelProps = {
  workspace: StoryWorkspace
  selectedNode: WorkspaceNode | null
  title: string
  content: string
  saveState: 'idle' | 'saving' | 'saved' | 'error'
  autoFollow?: boolean
  liveRunChapterLabel?: string | null
  detachedFromRun?: boolean
  onReturnToLiveRun?: () => void
  onTitleChange: (value: string) => void
  onContentChange: (value: string) => void
}

const nodeLabel: Record<NonNullable<WorkspaceNode['type']>, string> = {
  volume: '当前卷',
  chapter: '当前章节',
}

function getSaveLabel(saveState: WorkspaceEditorPanelProps['saveState']) {
  if (saveState === 'saving') return '正在保存'
  if (saveState === 'saved') return '已保存'
  if (saveState === 'error') return '保存失败'
  return '自动保存'
}

export function WorkspaceEditorPanel({ workspace, selectedNode, title, content, saveState, autoFollow = false, liveRunChapterLabel = null, detachedFromRun = false, onReturnToLiveRun, onTitleChange, onContentChange }: WorkspaceEditorPanelProps) {
  const wordCount = useMemo(() => content.replace(/\s/g, '').length, [content])
  const contentRef = useRef<HTMLDivElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const navigate = useNavigate()

  useLayoutEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = '0px'
    textarea.style.height = `${Math.max(textarea.scrollHeight, 520)}px`
  }, [content])

  useLayoutEffect(() => {
    if (!autoFollow || !contentRef.current) return
    contentRef.current.scrollTop = contentRef.current.scrollHeight
  }, [autoFollow, content])

  return (
    <section className='workspace-editor panel'>
      <div className='workspace-editor__tabbar'>
        <button type='button' className='workspace-editor__tab is-active'>
          <FileText size={15} />
          <span>{selectedNode?.title ?? workspace.title}</span>
          <MoreHorizontal size={14} />
        </button>
        <button type='button' className='workspace-editor__tab' onClick={() => navigate(`/stories/${workspace.storyId}/reference`)}>
          <Globe2 size={15} />
          <span>世界观设定</span>
        </button>
      </div>

      <div className='editor-panel__toolbar workspace-editor__toolbar'>
        <div className='workspace-editor__breadcrumbs'>
          <span>{selectedNode ? nodeLabel[selectedNode.type] : '当前节点'}</span>
          <strong>{selectedNode?.title ?? workspace.title}</strong>
        </div>
        <div className='editor-panel__toolbar-actions'>
          <div className='workspace-editor__format-actions' aria-label='文本工具'>
            <button type='button' aria-label='加粗' disabled>
              <Bold size={15} />
            </button>
            <button type='button' aria-label='斜体' disabled>
              <Italic size={15} />
            </button>
            <button type='button' aria-label='列表' disabled>
              <List size={15} />
            </button>
          </div>
          <span className='workspace-editor__word-count'>{wordCount.toLocaleString()} 字</span>
          <span className='workspace-editor__status'>{getSaveLabel(saveState)}</span>
        </div>
      </div>

      <div ref={contentRef} className='editor-panel__content workspace-editor__content'>
        {detachedFromRun && liveRunChapterLabel ? (
          <div className='workspace-editor__live-banner'>
            <div>
              <strong>AI 正在生成 {liveRunChapterLabel}</strong>
              <p>你当前正在回看其他章节，点击按钮可回到实时生成位置。</p>
            </div>
            <button type='button' className='secondary-button workspace-editor__live-button' onClick={onReturnToLiveRun}>
              回到正在生成
            </button>
          </div>
        ) : null}
        <input className='workspace-editor__title-input' value={title} onChange={(event) => onTitleChange(event.target.value)} placeholder='输入章节标题' />
        <div className='editor-panel__subhead muted'>
          <span>{workspace.localOnly ? '保存在当前浏览器' : '已连接工作台'}</span>
        </div>

        <div className='editor-panel__editor-wrap workspace-editor__wrap'>
          <textarea ref={textareaRef} className='editor-panel__textarea' value={content} onChange={(event) => onContentChange(event.target.value)} placeholder='在这里继续完善这一章的正文...' />
        </div>
      </div>
    </section>
  )
}

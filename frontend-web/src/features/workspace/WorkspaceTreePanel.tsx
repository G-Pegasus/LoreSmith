import { useEffect, useMemo, useState } from 'react'
import { BookOpen, ChevronDown, ChevronRight, FileText, FolderOpen, Globe2, Network, Plus, Sparkles } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { StoryWorkspace, WorkspaceNode, WorkspaceNodeType } from '../../lib/types/api'

type WorkspaceTreePanelProps = {
  workspace: StoryWorkspace
  activeNodeId: string | null
  onSelect: (nodeId: string) => void
  onCreateNode: (parentId: string | null, type: WorkspaceNodeType) => void
  onContinueRun: () => Promise<void>
  isBusy?: boolean
}

const typeLabel: Record<WorkspaceNodeType, string> = {
  volume: '卷',
  chapter: '章',
}

function chunkChapters(chapters: WorkspaceNode[]) {
  const chunks: WorkspaceNode[][] = []
  for (let index = 0; index < chapters.length; index += 10) {
    chunks.push(chapters.slice(index, index + 10))
  }
  return chunks
}

export function WorkspaceTreePanel({ workspace, activeNodeId, onSelect, onCreateNode, onContinueRun, isBusy = false }: WorkspaceTreePanelProps) {
  const [expandedVolumes, setExpandedVolumes] = useState<Record<string, boolean>>({})
  const [expandedChapterGroups, setExpandedChapterGroups] = useState<Record<string, boolean>>({})
  const navigate = useNavigate()
  const roots = useMemo(
    () => workspace.nodes.filter((node) => node.parentId === null && node.type === 'volume').sort((a, b) => a.order - b.order),
    [workspace.nodes],
  )
  const chaptersByVolume = useMemo(
    () =>
      roots.reduce<Record<string, WorkspaceNode[]>>((acc, volume) => {
        acc[volume.id] = workspace.nodes.filter((item) => item.parentId === volume.id && item.type === 'chapter').sort((a, b) => a.order - b.order)
        return acc
      }, {}),
    [roots, workspace.nodes],
  )
  const counts = {
    volumes: workspace.nodes.filter((node) => node.type === 'volume').length,
    chapters: workspace.nodes.filter((node) => node.type === 'chapter').length,
  }

  useEffect(() => {
    if (!activeNodeId) return
    const activeNode = workspace.nodes.find((node) => node.id === activeNodeId) ?? null
    const volumeId = activeNode?.type === 'volume' ? activeNode.id : activeNode?.parentId
    if (!volumeId) return
    setExpandedVolumes((current) => ({ ...current, [volumeId]: true }))
    const chapters = chaptersByVolume[volumeId] ?? []
    const chapterIndex = chapters.findIndex((chapter) => chapter.id === activeNodeId)
    if (chapterIndex >= 0) {
      const groupIndex = Math.floor(chapterIndex / 10)
      setExpandedChapterGroups((current) => ({ ...current, [`${volumeId}-${groupIndex}`]: true }))
    }
  }, [activeNodeId, chaptersByVolume, workspace.nodes])

  return (
    <aside className='workspace-sidebar panel'>
      <div className='workspace-sidebar__header'>
        <BookOpen size={17} />
        <h2>{workspace.title}</h2>
        <button type='button' className='workspace-sidebar__icon-button' aria-label='新建卷' onClick={() => onCreateNode(null, 'volume')}>
          <Plus size={16} />
        </button>
      </div>

      <div className='workspace-sidebar__meta workspace-sidebar__meta--stack'>
        <span>{counts.volumes} 卷</span>
        <span>{counts.chapters} 章</span>
        <span>{workspace.localOnly ? '本地草稿模式' : '云端工作台'}</span>
      </div>

      <div className='workspace-tree__utility' aria-label='创作资料'>
        <button type='button' className='workspace-tree__utility-item is-active'>
          <FolderOpen size={14} />
          <span>大纲与章节</span>
        </button>
        <button type='button' className='workspace-tree__utility-item' onClick={() => navigate(`/stories/${workspace.storyId}/reference`)}>
          <Globe2 size={14} />
          <span>世界观设定</span>
        </button>
        <button type='button' className='workspace-tree__utility-item' onClick={() => navigate(`/stories/${workspace.storyId}/reference`)}>
          <Network size={14} />
          <span>人物关系</span>
        </button>
      </div>

      <div className='workspace-tree'>
        {roots.map((volume) => {
          const chapters = chaptersByVolume[volume.id] ?? []
          const chapterGroups = chunkChapters(chapters)
          const isVolumeOpen = expandedVolumes[volume.id] ?? true

          return (
            <div key={volume.id} className='workspace-tree__branch'>
              <div className={`workspace-tree__node workspace-tree__node--volume ${activeNodeId === volume.id ? 'is-active' : ''}`}>
                <button
                  type='button'
                  className='workspace-tree__toggle'
                  aria-label={isVolumeOpen ? '收起卷' : '展开卷'}
                  onClick={() => setExpandedVolumes((current) => ({ ...current, [volume.id]: !(current[volume.id] ?? true) }))}
                >
                  {isVolumeOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                </button>
                <button type='button' className='workspace-tree__node-main' onClick={() => onSelect(volume.id)}>
                  <span className='workspace-tree__node-type'>
                    <FolderOpen size={14} />
                    {typeLabel.volume}
                  </span>
                  <span className='workspace-tree__node-title'>{volume.title}</span>
                </button>
              </div>

              {isVolumeOpen ? (
                <div className='workspace-tree__children'>
                  {chapterGroups.map((group, groupIndex) => {
                    const groupKey = `${volume.id}-${groupIndex}`
                    const isGroupOpen = expandedChapterGroups[groupKey] ?? groupIndex === 0
                    const start = groupIndex * 10 + 1
                    const end = start + group.length - 1
                    const hasActiveChapter = group.some((chapter) => chapter.id === activeNodeId)
                    return (
                      <div key={groupKey} className='workspace-tree__chapter-group'>
                        <button
                          type='button'
                          className={`workspace-tree__drawer ${hasActiveChapter ? 'is-active' : ''}`}
                          onClick={() => setExpandedChapterGroups((current) => ({ ...current, [groupKey]: !(current[groupKey] ?? groupIndex === 0) }))}
                        >
                          {isGroupOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                          <span>第 {start}-{end} 章</span>
                          <strong>{group.length}</strong>
                        </button>
                        {isGroupOpen ? (
                          <div className='workspace-tree__drawer-items'>
                            {group.map((chapter, index) => (
                              <button
                                key={chapter.id}
                                type='button'
                                className={`workspace-tree__node workspace-tree__node--chapter ${activeNodeId === chapter.id ? 'is-active' : ''}`}
                                onClick={() => onSelect(chapter.id)}
                              >
                                <span className='workspace-tree__node-type'>
                                  <FileText size={13} />
                                  {String(start + index).padStart(2, '0')}
                                </span>
                                <span className='workspace-tree__node-title'>{chapter.title}</span>
                              </button>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    )
                  })}
                </div>
              ) : null}

              {activeNodeId === volume.id ? (
                <div className='workspace-tree__actions'>
                  <button type='button' className='workspace-tree__add' onClick={() => onCreateNode(volume.id, 'chapter')}>
                    <Plus size={13} />
                    新建章
                  </button>
                </div>
              ) : null}
            </div>
          )
        })}
      </div>

      <div className='workspace-sidebar__footer'>
        <button type='button' className='workspace-sidebar__continue' disabled={isBusy} onClick={() => void onContinueRun()}>
          <Sparkles size={16} />
          <span>{isBusy ? 'AI 正在写作' : 'AI 续写下一章'}</span>
        </button>
      </div>
    </aside>
  )
}

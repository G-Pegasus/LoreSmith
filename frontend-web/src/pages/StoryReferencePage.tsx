import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { fetchStoryReferenceDetail, fetchStoryWorkspace } from '../lib/api/workspace'
import type { ArcSummary, CharacterSnapshot, StoryReferenceDetail, VolumePlan, VolumeSummary, WorkspaceCharacterItem, WorkspaceForeshadowItem, WorkspaceOutlineItem } from '../lib/types/api'
import './pages.css'

function readText(value: unknown, fallback: string | number = '未提供') {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return String(value)
  }
  const text = typeof value === 'string' ? value.trim() : ''
  return text || String(fallback)
}

function groupForeshadow(items: WorkspaceForeshadowItem[]) {
  const groups: Record<string, WorkspaceForeshadowItem[]> = { planted: [], advanced: [], resolved: [], other: [] }
  items.forEach((item) => {
    const status = String(item.status ?? '').trim().toLowerCase()
    if (status === 'planted') groups.planted.push(item)
    else if (status === 'advanced') groups.advanced.push(item)
    else if (status === 'resolved') groups.resolved.push(item)
    else groups.other.push(item)
  })
  return groups
}

function snapshotByName(snapshots: CharacterSnapshot[]) {
  return snapshots.reduce<Record<string, CharacterSnapshot>>((acc, item) => {
    const name = String(item.name ?? '').trim()
    if (name) acc[name] = item
    return acc
  }, {})
}

function summaryByVolume(volumeSummaries: VolumeSummary[]) {
  return volumeSummaries.reduce<Record<number, VolumeSummary>>((acc, item) => {
    const key = Number(item.volume ?? 0)
    if (key > 0) acc[key] = item
    return acc
  }, {})
}

function arcsByVolume(arcSummaries: ArcSummary[]) {
  return arcSummaries.reduce<Record<number, ArcSummary[]>>((acc, item) => {
    const key = Number(item.volume ?? 0)
    if (!acc[key]) acc[key] = []
    acc[key].push(item)
    return acc
  }, {})
}

function ReferenceHero({ detail }: { detail: StoryReferenceDetail }) {
  return (
    <section className='reference-page__hero panel'>
      <div>
        <div className='workspace-sidebar__eyebrow'>作品资料总览</div>
        <h1 className='reference-page__title'>{detail.title || '未命名作品'}</h1>
        <p className='reference-page__summary'>{readText(detail.premise, '暂无作品设定')}</p>
      </div>
      <div className='reference-page__hero-stats'>
        <div className='reference-stat panel'>
          <span>已完成章节</span>
          <strong>{detail.progress.completedChapters}</strong>
        </div>
        <div className='reference-stat panel'>
          <span>当前章节</span>
          <strong>{detail.progress.currentChapter || '-'}</strong>
        </div>
        <div className='reference-stat panel'>
          <span>总字数</span>
          <strong>{detail.progress.totalWordCount || 0}</strong>
        </div>
        <div className='reference-stat panel'>
          <span>当前卷</span>
          <strong>{detail.progress.currentVolume || '-'}</strong>
        </div>
      </div>
    </section>
  )
}

function ReferenceNav() {
  const items = [
    { href: '#reference-overview', label: '全书' },
    { href: '#reference-volumes', label: '卷规划' },
    { href: '#reference-outline', label: '章纲' },
    { href: '#reference-characters', label: '人物' },
    { href: '#reference-foreshadow', label: '伏笔' },
    { href: '#reference-world', label: '设定' },
  ]
  return (
    <nav className='reference-page__nav panel' aria-label='作品资料导航'>
      {items.map((item) => (
        <a key={item.href} href={item.href}>
          {item.label}
        </a>
      ))}
    </nav>
  )
}

function VolumePlanCard({ volume, summary, arcs }: { volume: VolumePlan; summary?: VolumeSummary; arcs: ArcSummary[] }) {
  const plannedChapters = volume.arcs.reduce((count, arc) => count + Number(arc.estimatedChapters ?? 0), 0)
  return (
    <article className='reference-volume-card panel'>
      <div className='reference-volume-card__header'>
        <div>
          <div className='workspace-sidebar__eyebrow'>第 {volume.index ?? 0} 卷</div>
          <h3>{readText(volume.title, '未命名卷')}</h3>
        </div>
        <span className='status-badge'>{plannedChapters || volume.arcs.length || 0} 章规划</span>
      </div>
      <p className='reference-volume-card__theme'>{readText(volume.theme, '暂无本卷主题')}</p>
      {summary?.summary ? <p className='reference-volume-card__summary'>{summary.summary}</p> : null}
      <div className='reference-volume-card__meta'>
        {volume.final ? <span>终卷</span> : null}
        {arcs.length ? <span>{arcs.length} 个 arc 摘要</span> : null}
      </div>
      <div className='reference-volume-card__arcs'>
        {volume.arcs.length ? volume.arcs.map((arc) => (
          <div key={`${volume.index}-${arc.index}-${arc.title}`} className='reference-chip-card'>
            <strong>{readText(arc.title, '未命名 arc')}</strong>
            <p>{readText(arc.goal, '暂无目标')}</p>
            <span>{arc.estimatedChapters || arc.chapters.length || 0} 章</span>
          </div>
        )) : <p className='workspace-reference-empty'>暂无分段规划。</p>}
      </div>
    </article>
  )
}

function CharacterCard({ item, snapshot }: { item: WorkspaceCharacterItem; snapshot?: CharacterSnapshot }) {
  return (
    <article className='reference-character-card panel'>
      <div className='reference-character-card__header'>
        <div>
          <h3>{readText(item.name, '未命名角色')}</h3>
          <span>{readText(item.role, '未标注角色定位')}</span>
        </div>
        <span className='status-badge'>{readText(item.tier, 'important')}</span>
      </div>
      <p>{readText(item.description, '暂无人物描述')}</p>
      {item.arc ? <div className='reference-character-card__block'><strong>角色弧光</strong><p>{item.arc}</p></div> : null}
      {item.traits?.length ? <div className='reference-character-card__chips'>{item.traits.map((trait) => <span key={trait} className='chip-button'>{trait}</span>)}</div> : null}
      {item.aliases?.length ? <div className='reference-character-card__meta'>别名：{item.aliases.join('、')}</div> : null}
      {snapshot?.status || snapshot?.motivation || snapshot?.relations ? (
        <div className='reference-character-card__snapshot'>
          <strong>当前状态</strong>
          <p>{readText(snapshot.status, '未记录状态')}</p>
          {snapshot.motivation ? <span>动机：{snapshot.motivation}</span> : null}
          {snapshot.relations ? <span>关系：{snapshot.relations}</span> : null}
        </div>
      ) : null}
    </article>
  )
}

function OutlineCard({ item, index }: { item: WorkspaceOutlineItem; index: number }) {
  return (
    <article className='reference-outline-card'>
      <div className='reference-outline-card__header'>
        <strong>第 {readText(item.chapter, index + 1)} 章</strong>
        {item.title ? <span>{item.title}</span> : null}
      </div>
      <p>{readText(item.core_event, '暂无核心事件')}</p>
      {item.hook ? <em>{item.hook}</em> : null}
      {item.scenes?.length ? (
        <div className='reference-outline-card__scenes'>
          {item.scenes.map((scene) => (
            <span key={scene}>{scene}</span>
          ))}
        </div>
      ) : null}
    </article>
  )
}

export function StoryReferencePage() {
  const { storyId = '' } = useParams()
  const workspaceQuery = useQuery({ queryKey: ['story-workspace', storyId], queryFn: () => fetchStoryWorkspace(storyId), enabled: Boolean(storyId) })
  const detailQuery = useQuery({ queryKey: ['story-reference-detail', storyId], queryFn: () => fetchStoryReferenceDetail(storyId, workspaceQuery.data), enabled: Boolean(storyId) })

  const detail = detailQuery.data
  const foreshadowGroups = useMemo(() => groupForeshadow(detail?.foreshadowLedger ?? []), [detail?.foreshadowLedger])
  const snapshots = useMemo(() => snapshotByName(detail?.characterSnapshots ?? []), [detail?.characterSnapshots])
  const volumeSummaryMap = useMemo(() => summaryByVolume(detail?.volumeSummaries ?? []), [detail?.volumeSummaries])
  const arcSummaryMap = useMemo(() => arcsByVolume(detail?.arcSummaries ?? []), [detail?.arcSummaries])

  if (workspaceQuery.isLoading || detailQuery.isLoading) {
    return <div className='panel page-empty'>正在加载作品资料...</div>
  }

  if (workspaceQuery.isError || detailQuery.isError || !detail) {
    return <div className='panel page-empty'>作品资料加载失败，请稍后重试。</div>
  }

  return (
    <section className='reference-page'>
      <div className='reference-page__topbar'>
        <Link to={`/stories/${storyId}/workspace`} className='secondary-button reference-page__back'>返回工作台</Link>
      </div>

      <ReferenceHero detail={detail} />
      <ReferenceNav />

      <section id='reference-overview' className='reference-page__section panel'>
        <div className='reference-page__section-header'>
          <div>
            <div className='workspace-sidebar__eyebrow'>全书规划</div>
            <h2>全书方向与结构</h2>
          </div>
          <span className='status-badge'>{detail.layeredOutline.length || detail.outline.length} 个结构单元</span>
        </div>
        <div className='reference-page__overview-grid'>
          <article className='reference-overview-card'>
            <strong>结局方向</strong>
            <p>{readText(detail.compass.endingDirection, '暂无结局方向')}</p>
          </article>
          <article className='reference-overview-card'>
            <strong>预计体量</strong>
            <p>{readText(detail.compass.estimatedScale, '暂无体量规划')}</p>
          </article>
          <article className='reference-overview-card'>
            <strong>未完线索</strong>
            <p>{detail.compass.openThreads.length ? detail.compass.openThreads.join('；') : '暂无未完线索'}</p>
          </article>
        </div>
      </section>

      <section id='reference-volumes' className='reference-page__section'>
        <div className='reference-page__section-header'>
          <div>
            <div className='workspace-sidebar__eyebrow'>卷规划</div>
            <h2>每卷规划</h2>
          </div>
        </div>
        <div className='reference-volume-grid'>
          {detail.layeredOutline.length ? detail.layeredOutline.map((volume) => (
            <VolumePlanCard
              key={`volume-${volume.index}-${volume.title}`}
              volume={volume}
              summary={volumeSummaryMap[Number(volume.index ?? 0)]}
              arcs={arcSummaryMap[Number(volume.index ?? 0)] ?? []}
            />
          )) : (
            <div className='panel workspace-empty'>暂无分卷规划，可先查看基础章纲。</div>
          )}
        </div>
      </section>

      <section id='reference-outline' className='reference-page__section panel'>
        <div className='reference-page__section-header'>
          <div>
            <div className='workspace-sidebar__eyebrow'>章节任务</div>
            <h2>基础章纲</h2>
          </div>
          <span className='status-badge'>{detail.outline.length} 章</span>
        </div>
        <div className='reference-outline-grid'>
          {detail.outline.length ? detail.outline.map((item, index) => (
            <OutlineCard key={`outline-${readText(item.chapter, index)}-${item.title ?? index}`} item={item} index={index} />
          )) : <p className='workspace-reference-empty'>暂无基础章纲。</p>}
        </div>
      </section>

      <section id='reference-characters' className='reference-page__section'>
        <div className='reference-page__section-header'>
          <div>
            <div className='workspace-sidebar__eyebrow'>角色卡</div>
            <h2>人物</h2>
          </div>
        </div>
        <div className='reference-character-grid'>
          {detail.characters.length ? detail.characters.map((item, index) => (
            <CharacterCard key={`${item.name ?? 'character'}-${index}`} item={item} snapshot={snapshots[String(item.name ?? '')]} />
          )) : <div className='panel workspace-empty'>暂无人物资料。</div>}
        </div>
      </section>

      <section id='reference-foreshadow' className='reference-page__section panel'>
        <div className='reference-page__section-header'>
          <div>
            <div className='workspace-sidebar__eyebrow'>伏笔板</div>
            <h2>伏笔</h2>
          </div>
        </div>
        <div className='reference-foreshadow-grid'>
          {(['planted', 'advanced', 'resolved', 'other'] as const).map((key) => (
            <div key={key} className='reference-foreshadow-column'>
              <strong>{key === 'planted' ? '已埋下' : key === 'advanced' ? '推进中' : key === 'resolved' ? '已回收' : '其他'}</strong>
              <div className='workspace-reference-list'>
                {foreshadowGroups[key].length ? foreshadowGroups[key].map((item, index) => (
                  <div key={`${item.id ?? key}-${index}`} className='workspace-reference-item'>
                    <strong>{readText(item.id, '未命名伏笔')}</strong>
                    <p>{readText(item.description, '暂无伏笔说明')}</p>
                    <span>埋下：{item.planted_at || '-'} / 回收：{item.resolved_at || '-'}</span>
                  </div>
                )) : <p className='workspace-reference-empty'>暂无内容。</p>}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section id='reference-world' className='reference-page__section reference-page__section--split reference-page__section--triple'>
        <div className='panel reference-page__subpanel'>
          <div className='reference-page__section-header'>
            <div>
              <div className='workspace-sidebar__eyebrow'>世界设定</div>
              <h2>规则</h2>
            </div>
          </div>
          <div className='workspace-reference-list'>
            {detail.worldRules.length ? detail.worldRules.map((item, index) => (
              <div key={`world-${index}`} className='workspace-reference-item'>
                <strong>{readText(item.category, `规则 ${index + 1}`)}</strong>
                <p>{readText(item.rule, '暂无规则说明')}</p>
                {item.boundary ? <span>{item.boundary}</span> : null}
              </div>
            )) : <p className='workspace-reference-empty'>暂无世界规则。</p>}
          </div>
        </div>
        <div className='panel reference-page__subpanel'>
          <div className='reference-page__section-header'>
            <div>
              <div className='workspace-sidebar__eyebrow'>人物关系</div>
              <h2>关系</h2>
            </div>
          </div>
          <div className='workspace-reference-list'>
            {detail.relationshipState.length ? detail.relationshipState.map((item, index) => (
              <div key={`rel-${index}`} className='workspace-reference-item'>
                <strong>{readText(item.character_a, '角色A')} × {readText(item.character_b, '角色B')}</strong>
                <p>{readText(item.relation, '暂无关系说明')}</p>
                {item.chapter ? <span>章节：{item.chapter}</span> : null}
              </div>
            )) : <p className='workspace-reference-empty'>暂无人物关系。</p>}
          </div>
        </div>
        <div className='panel reference-page__subpanel'>
          <div className='reference-page__section-header'>
            <div>
              <div className='workspace-sidebar__eyebrow'>时间线</div>
              <h2>事件</h2>
            </div>
          </div>
          <div className='workspace-reference-list'>
            {detail.timeline.length ? detail.timeline.map((item, index) => (
              <div key={`timeline-${index}`} className='workspace-reference-item'>
                <strong>{readText(item.time, `节点 ${index + 1}`)}</strong>
                <p>{readText(item.event, '暂无事件说明')}</p>
                {item.chapter ? <span>章节：{item.chapter}</span> : null}
                {item.characters?.length ? <span>{item.characters.join('、')}</span> : null}
              </div>
            )) : <p className='workspace-reference-empty'>暂无时间线。</p>}
          </div>
        </div>
      </section>
    </section>
  )
}

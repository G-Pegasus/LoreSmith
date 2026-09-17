import { CheckCircle2, ClipboardList } from 'lucide-react'
import type { InspirationSettings } from '../../lib/types/api'

type SettingConfirmSheetProps = {
  settings: InspirationSettings
  revision: number
  confirmedSettings: InspirationSettings | null
  /** 对话进行中：卡片暂时不可点 */
  locked: boolean
  /** 本地已确认态（服务端确认后指针会清空，所以这是纯前端状态） */
  confirmed: boolean
  submitting: boolean
  onConfirm: () => void
}

/** 「设定 N / 4 项」里的 N —— 与后端四槽位判定保持同一套定义。 */
export function countSettingsSlots(settings: InspirationSettings | null | undefined) {
  if (!settings) return 0
  let count = 0
  if (settings.title?.trim()) count += 1
  if (settings.worldSetting?.trim()) count += 1
  if (settings.characters?.length) count += 1
  if (settings.synopsis?.trim()) count += 1
  return count
}

function textDiff(next: string | undefined, prev: string | undefined) {
  if (!next?.trim() || !prev?.trim()) return '新增'
  return next.trim() === prev.trim() ? null : '已修改'
}

function characterDiff(character: { name: string; role: string; description: string }, settings: InspirationSettings) {
  const previous = settings.characters?.find((item) => item.name === character.name)
  if (!previous) return '新增'
  return previous.role !== character.role || previous.description !== character.description ? '已修改' : null
}

function DiffTag({ label }: { label: string | null }) {
  if (!label) return null
  return <span className={`setting-sheet__diff setting-sheet__diff--${label === '新增' ? 'new' : 'changed'}`}>{label}</span>
}

export function SettingConfirmSheet({
  settings,
  revision,
  confirmedSettings,
  locked,
  confirmed,
  submitting,
  onConfirm,
}: SettingConfirmSheetProps) {
  const slotCount = countSettingsSlots(settings)
  const characters: Array<{ name: string; role: string; description: string }> = settings.characters ?? []

  return (
    <section className={`setting-sheet${confirmed ? ' setting-sheet--confirmed' : ''}`}>
      <header className='setting-sheet__header'>
        <div className='setting-sheet__heading'>
          <ClipboardList size={15} />
          <strong>设定确认单</strong>
        </div>
        <span className='setting-sheet__meta'>
          {confirmed ? (
            <>
              <CheckCircle2 size={13} /> 已填入工作台 · 第 {revision} 版
            </>
          ) : (
            `第 ${revision} 版 · ${slotCount} / 4 项`
          )}
        </span>
      </header>

      <div className='setting-sheet__items'>
        <div className='setting-sheet__item'>
          <div className='setting-sheet__label'>
            <span>作品标题</span>
            {confirmed ? null : <DiffTag label={textDiff(settings.title, confirmedSettings?.title)} />}
          </div>
          <p className='setting-sheet__value'>{settings.title}</p>
        </div>

        <div className='setting-sheet__item'>
          <div className='setting-sheet__label'>
            <span>世界观设定</span>
            {confirmed ? null : <DiffTag label={textDiff(settings.worldSetting, confirmedSettings?.worldSetting)} />}
          </div>
          <p className='setting-sheet__value'>{settings.worldSetting}</p>
        </div>

        <div className='setting-sheet__item'>
          <div className='setting-sheet__label'>
            <span>角色设定 · {characters.length} 个</span>
          </div>
          <div className='setting-sheet__characters'>
            {characters.map((character) => (
              <div key={character.name} className='setting-sheet__character'>
                <div className='setting-sheet__character-head'>
                  <strong>{character.name}</strong>
                  {character.role ? <em>{character.role}</em> : null}
                  {confirmed || !confirmedSettings ? null : <DiffTag label={characterDiff(character, confirmedSettings)} />}
                </div>
                <p>{character.description}</p>
              </div>
            ))}
          </div>
        </div>

        <div className='setting-sheet__item'>
          <div className='setting-sheet__label'>
            <span>故事简介</span>
            {confirmed ? null : <DiffTag label={textDiff(settings.synopsis, confirmedSettings?.synopsis)} />}
          </div>
          <p className='setting-sheet__value'>{settings.synopsis}</p>
        </div>
      </div>

      <footer className='setting-sheet__footer'>
        <button
          className='primary-button setting-sheet__confirm'
          type='button'
          disabled={locked || confirmed || submitting}
          onClick={onConfirm}
        >
          {confirmed ? '已填入工作台' : submitting ? '填入中…' : '确认并填入工作台'}
        </button>
        {locked && !confirmed ? <span className='setting-sheet__hint'>对话进行中，完成后可确认</span> : null}
      </footer>
    </section>
  )
}

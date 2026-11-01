import type { TaskType } from '../types'
import { Icon } from './Icon'
import type { IconName } from './Icon'

const tasks: Array<{ value: TaskType; icon: IconName; title: string; description: string }> = [
  { value: 'risk', icon: 'pulse', title: '风险预测', description: '查看未来 24 小时模型预测' },
  { value: 'similar', icon: 'search', title: '相似病例', description: '寻找病程可比的历史记录' },
  { value: 'combined', icon: 'layers', title: '联合评估', description: '结合风险、病例与来源证据' },
]

export function TaskPicker({ value, disabled, onChange }: { value: TaskType; disabled: boolean; onChange: (task: TaskType) => void }) {
  return <div className="task-options" role="radiogroup" aria-label="评估任务">
    {tasks.map((item, index) => (
      <button
        key={item.value}
        type="button"
        role="radio"
        aria-checked={value === item.value}
        aria-label={item.title + '：' + item.description}
        title={item.description}
        tabIndex={value === item.value ? 0 : -1}
        className={`task-option ${value === item.value ? 'selected' : ''}`}
        disabled={disabled}
        onClick={() => onChange(item.value)}
        onKeyDown={(event) => {
          let next: number
          if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % tasks.length
          else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index + tasks.length - 1) % tasks.length
          else if (event.key === 'Home') next = 0
          else if (event.key === 'End') next = tasks.length - 1
          else return
          event.preventDefault()
          onChange(tasks[next].value)
          event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('button')[next]?.focus()
        }}
      >
        <Icon name={item.icon} size={16} />
        <span>{item.title}</span>
      </button>
    ))}
  </div>
}

'use client'

import * as React from 'react'
import { cn } from 'ui'

import { Index } from '@/__registry__'
import { useConfig } from '@/hooks/use-config'
import { styles } from '@/registry/styles'

interface ComponentPreviewProps extends React.HTMLAttributes<HTMLDivElement> {
  name: string
  extractClassname?: boolean
  extractedClassNames?: string
  align?: 'center' | 'start' | 'end'
  peekCode?: boolean
  showGrid?: boolean
  showDottedGrid?: boolean
  wide?: boolean
}

interface DisplayOptions {
  align?: 'center' | 'start' | 'end'
  peekCode?: boolean
  showGrid?: boolean
  showDottedGrid?: boolean
  wide?: boolean
}

export function CodeFragment({
  name,
  children,
  className,
  extractClassname,
  extractedClassNames,
  align = 'center',
  peekCode = false,
  showGrid = false,
  showDottedGrid = true,
  wide = false,
  ...props
}: ComponentPreviewProps) {
  const displayOptions: DisplayOptions = {
    align,
    peekCode,
    showGrid,
    showDottedGrid,
    wide,
  }

  const [config] = useConfig()
  const index = styles.findIndex((style) => style.name === config.style)

  const Codes = React.Children.toArray(children) as React.ReactElement[]
  const Code = Codes[index]

  const [expand, setExpandState] = React.useState(false)

  const Preview = React.useMemo(() => {
    const Component = Index[config.style][name]?.component

    if (!Component) {
      return null
    }

    return (
      <div className={cn(className, extractedClassNames)} {...props}>
        <Component {...displayOptions} />
      </div>
    )
  }, [className, config.style, extractedClassNames, name, props, displayOptions])

  return (
    <div>
      {Preview}
      <button onClick={() => setExpandState(!expand)}>
        {expand ? 'Collapse' : 'Expand'}
      </button>
    </div>
  )
}
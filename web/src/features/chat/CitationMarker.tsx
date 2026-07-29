interface CitationMarkerProps {
  index: number
  onClick: (index: number) => void
}

export function CitationMarker({ index, onClick }: CitationMarkerProps) {
  return (
    <button
      type="button"
      className="inline-flex items-center justify-center rounded px-1 text-[10px] font-semibold leading-none text-primary hover:text-primary/80 bg-primary/10 hover:bg-primary/20 cursor-pointer align-super transition-colors duration-150 min-w-[1.1rem]"
      onClick={() => onClick(index)}
      aria-label={`Jump to source ${index}`}
    >
      {index}
    </button>
  )
}

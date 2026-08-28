import mark from '../assets/blendrender-mark.png'

export function Brand() {
  return (
    <div className="brand" aria-label="BlendRender">
      <img src={mark} alt="" className="brand__mark" />
      <span>BlendRender</span>
    </div>
  )
}

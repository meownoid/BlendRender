import mark from '../assets/blendqueue-mark.png'

export function Brand() {
  return (
    <div className="brand" aria-label="BlendQueue">
      <img src={mark} alt="" className="brand__mark" />
      <span>BlendQueue</span>
    </div>
  )
}


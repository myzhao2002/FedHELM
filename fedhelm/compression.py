"""Top-50% magnitude sparsity, blockwise signed INT8, canonical SHA256."""
import hashlib
import json
import math
from pydantic import BaseModel,ConfigDict,Field,model_validator


def digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


class Packet(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    dimensions:int=Field(ge=4,le=200000)
    block_size:int=Field(default=256,ge=256,le=256)
    indices:list[int]=Field(max_length=100000)
    values:list[int]=Field(max_length=100000)
    scales:list[float]=Field(max_length=782)
    sha256:str

    @model_validator(mode='after')
    def validate_packet(self):
        if len(self.indices)!=math.ceil(self.dimensions*.5) or len(self.indices)!=len(self.values):raise ValueError('稀疏增量长度错误')
        if self.indices!=sorted(set(self.indices)) or any(i<0 or i>=self.dimensions for i in self.indices):raise ValueError('非法或重复索引')
        if any(v<-127 or v>127 for v in self.values):raise ValueError('量化值超出INT8范围')
        if len(self.scales)!=math.ceil(self.dimensions/256) or any(s<0 for s in self.scales):raise ValueError('分块尺度错误')
        if digest(self.model_dump(exclude={'sha256'}))!=self.sha256:raise ValueError('增量校验失败')
        return self


def encode(delta):
    indices=sorted(sorted(range(len(delta)),key=lambda i:abs(delta[i]),reverse=True)[:math.ceil(len(delta)*.5)])
    scales=[max(abs(v) for v in delta[start:start+256])/127 for start in range(0,len(delta),256)]
    values=[round(delta[i]/scales[i//256]) if scales[i//256] else 0 for i in indices]
    data={'dimensions':len(delta),'block_size':256,'indices':indices,'values':values,'scales':scales}
    return Packet(**data,sha256=digest(data))


def decode(packet):
    output=[0.]*packet.dimensions
    for i,v in zip(packet.indices,packet.values):output[i]=v*packet.scales[i//256]
    return output

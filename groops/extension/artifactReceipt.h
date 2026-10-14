// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_ARTIFACT_RECEIPT_H
#define ORBIT_POC_ARTIFACT_RECEIPT_H
#include <array>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <string>
#include <vector>
#include "base/import.h"
#ifndef GROOPS_DISABLE_Z
namespace orbitPocZlib {
#include <zlib.h>
}
#endif

namespace orbitPocQr
{
// Streaming SHA-256 for generated-artifact deletion receipts. Hashing is an
// output-lifecycle operation and never changes the numerical row stream.
class ArtifactSha256
{
  std::array<std::uint32_t,8> h{{0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19}};
  std::array<unsigned char,64> buffer{};
  std::uint64_t length=0;
  std::size_t buffered=0;
  static std::uint32_t rotate(std::uint32_t x,unsigned n){return (x>>n)|(x<<(32-n));}
  void block(const unsigned char *p)
  {
    static const std::uint32_t k[64]={
      0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
      0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
      0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
      0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
      0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
      0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
      0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
      0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
    std::uint32_t w[64];
    for(unsigned i=0;i<16;i++)w[i]=(std::uint32_t(p[4*i])<<24)|(std::uint32_t(p[4*i+1])<<16)|(std::uint32_t(p[4*i+2])<<8)|p[4*i+3];
    for(unsigned i=16;i<64;i++)
    {const auto s0=rotate(w[i-15],7)^rotate(w[i-15],18)^(w[i-15]>>3);const auto s1=rotate(w[i-2],17)^rotate(w[i-2],19)^(w[i-2]>>10);w[i]=w[i-16]+s0+w[i-7]+s1;}
    auto a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],hh=h[7];
    for(unsigned i=0;i<64;i++)
    {const auto t1=hh+(rotate(e,6)^rotate(e,11)^rotate(e,25))+((e&f)^(~e&g))+k[i]+w[i];const auto t2=(rotate(a,2)^rotate(a,13)^rotate(a,22))+((a&b)^(a&c)^(b&c));hh=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;}
    h[0]+=a;h[1]+=b;h[2]+=c;h[3]+=d;h[4]+=e;h[5]+=f;h[6]+=g;h[7]+=hh;
  }
public:
  void update(const unsigned char *p,std::size_t count)
  {length+=count;for(std::size_t i=0;i<count;i++){buffer[buffered++]=p[i];if(buffered==64){block(buffer.data());buffered=0;}}}
  std::string finish()
  {
    const std::uint64_t bits=length*8;buffer[buffered++]=0x80;
    if(buffered>56){while(buffered<64)buffer[buffered++]=0;block(buffer.data());buffered=0;}
    while(buffered<56)buffer[buffered++]=0;
    for(unsigned i=0;i<8;i++)buffer[56+i]=static_cast<unsigned char>(bits>>(56-8*i));
    block(buffer.data());std::ostringstream out;out<<std::hex<<std::setfill('0');for(auto value:h)out<<std::setw(8)<<value;return out.str();
  }
};
struct ArtifactReceipt{std::string path,role,sha256;std::uint64_t bytes;};
inline ArtifactReceipt inspectArtifact(const std::string &path,const std::string &role)
{
  std::ifstream in(path,std::ios::binary);if(!in)throw(Exception("Cannot hash superseded QR artifact "+path));
  ArtifactSha256 digest;std::array<unsigned char,65536> data;std::uint64_t count=0;
  while(in){in.read(reinterpret_cast<char*>(data.data()),data.size());const auto size=in.gcount();if(size>0){digest.update(data.data(),size);count+=size;}}
  if(!in.eof())throw(Exception("Cannot finish hashing superseded QR artifact "+path));
  return {path,role,digest.finish(),count};
}
inline void compressRowProvenance(const std::string &source)
{
#ifdef GROOPS_DISABLE_Z
  throw(Exception("v3.1 row compression requires the existing zlib dependency"));
#else
  const auto target=source+".gz",pending=target+".pending",receipt=source+".compression.json";
  if(std::ifstream(target,std::ios::binary))throw(Exception("Refusing to replace completed compressed row provenance"));
  std::ifstream input(source,std::ios::binary);if(!input)throw(Exception("Cannot read completed row provenance"));
  orbitPocZlib::gzFile output=orbitPocZlib::gzopen(pending.c_str(),"wb6");if(!output)throw(Exception("Cannot create compressed row provenance"));
  ArtifactSha256 originalHash;std::uint64_t originalBytes=0;std::array<unsigned char,65536> data;
  try
  {
    while(input)
    {
      input.read(reinterpret_cast<char*>(data.data()),data.size());const auto count=input.gcount();
      if(count>0)
      {originalHash.update(data.data(),count);originalBytes+=count;if(orbitPocZlib::gzwrite(output,data.data(),count)!=count)throw(Exception("Cannot compress row provenance"));}
    }
    if(!input.eof())throw(Exception("Cannot finish reading row provenance"));
    const int closed=orbitPocZlib::gzclose(output);output=nullptr;if(closed!=Z_OK)throw(Exception("Cannot finish gzip row provenance"));
  }
  catch(...){if(output)orbitPocZlib::gzclose(output);throw;}
  const auto digest=originalHash.finish();orbitPocZlib::gzFile check=orbitPocZlib::gzopen(pending.c_str(),"rb");if(!check)throw(Exception("Cannot verify gzip row provenance"));
  ArtifactSha256 decodedHash;std::uint64_t decodedBytes=0;Bool valid=TRUE;
  for(;;)
  {
    const int count=orbitPocZlib::gzread(check,data.data(),data.size());
    if(count>0){decodedHash.update(data.data(),count);decodedBytes+=count;continue;}
    int error=0;orbitPocZlib::gzerror(check,&error);valid=count==0&&orbitPocZlib::gzeof(check)&&error==Z_OK;break;
  }
  valid=(orbitPocZlib::gzclose(check)==Z_OK)&&valid;
  if(!valid||decodedBytes!=originalBytes||decodedHash.finish()!=digest)throw(Exception("Compressed row provenance failed CRC/SHA round-trip verification"));
  if(std::rename(pending.c_str(),target.c_str())!=0)throw(Exception("Cannot publish compressed row provenance"));
  const auto packed=inspectArtifact(target,"closed_native_row_provenance");
  const auto receiptPending=receipt+".tmp";std::ofstream record(receiptPending);
  record<<"{\"policy\":\"verified_row_compression_v1\",\"role\":\"closed_native_row_provenance\",\"compression_level\":6,\"source\":{\"path\":"<<std::quoted(source)
        <<",\"sha256\":\""<<digest<<"\",\"bytes\":"<<originalBytes<<"},\"compressed\":{\"path\":"<<std::quoted(target)
        <<",\"sha256\":\""<<packed.sha256<<"\",\"bytes\":"<<packed.bytes<<"},\"round_trip_verified\":true,\"crc_verified\":true}\n";
  record.close();if(!record||std::rename(receiptPending.c_str(),receipt.c_str())!=0)throw(Exception("Cannot record lossless row compression"));
  if(std::remove(source.c_str())!=0)throw(Exception("Cannot release verified uncompressed row provenance"));
#endif
}
inline void writeRetentionReceipt(const std::string &path,const std::vector<ArtifactReceipt> &artifacts,Bool completed)
{
  const auto pending=path+".tmp";std::ofstream out(pending);
  out<<"{\"schema\":\"orbit-poc-native-factor-retention-v1\",\"status\":\""<<(completed?"completed":"planned")<<"\",\"artifacts\":[";
  for(UInt i=0;i<artifacts.size();i++){if(i)out<<',';const auto &a=artifacts[i];out<<"{\"path\":"<<std::quoted(a.path)<<",\"role\":"<<std::quoted(a.role)<<",\"sha256\":\""<<a.sha256<<"\",\"bytes\":"<<a.bytes<<'}';}
  out<<"]}\n";out.close();if(!out||std::rename(pending.c_str(),path.c_str())!=0)throw(Exception("Cannot save QR retention receipt"));
}
}
#endif

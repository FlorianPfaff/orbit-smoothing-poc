// Proposed standalone serializer regression; not compiled/executed by draft03.
#include "wideInterpolationExport.h"
#include <sstream>
#include <iostream>
#include <limits>
using namespace OrbitPoc;
static void require(bool ok,const char *message){if(!ok)throw std::runtime_error(message);}
int main()
{
  using namespace WideInterpolation;
  auto exact=WideInterpolationExport::identity(3);
  std::ostringstream stream;stream.precision(7);const auto flags=stream.flags();
  WideInterpolationExport::stencil(stream,exact,5);
  require(stream.str().find("\"mode\":\"exact\"")!=std::string::npos,"exact mode missing");
  require(stream.str().find("\"anchor\":null")!=std::string::npos,"invented exact anchor");
  require(stream.precision()==7&&stream.flags()==flags,"serializer changed stream format");
  Stencil s;s.mode=Mode::anchoredTwofold;s.indices={4,1};s.anchor=1;
  s.weights={{.5L,std::ldexp(1.L,-70)},{.5L,0.L}};
  std::ostringstream anchor;WideInterpolationExport::stencil(anchor,s,5);
  require(anchor.str().find("\"anchor\":1")!=std::string::npos,"actual local anchor lost");
  require(anchor.str().find("\"anchored_twofold\"")!=std::string::npos,"anchored mode lost");
  std::cout<<stream.str()<<'\n'<<anchor.str()<<'\n'; // Later exact decoder roundtrip input.
  bool rejected=false;s.anchor=2;
  try{WideInterpolationExport::stencil(anchor,s,5);}catch(const std::runtime_error&){rejected=true;}
  require(rejected,"invalid anchor accepted");
  rejected=false;s.anchor=1;s.indices[1]=4;
  try{WideInterpolationExport::stencil(anchor,s,5);}catch(const std::runtime_error&){rejected=true;}
  require(rejected,"repeated index accepted");
  rejected=false;s.indices={4,1};s.weights[0].low=std::numeric_limits<long double>::infinity();
  try{WideInterpolationExport::stencil(anchor,s,5);}catch(const std::runtime_error&){rejected=true;}
  require(rejected,"nonfinite component accepted");
}

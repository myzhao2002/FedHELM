$ErrorActionPreference='Stop'
Add-Type @'
using System; using System.Runtime.InteropServices;
public static class ActiveVisio {
 [DllImport("ole32.dll",CharSet=CharSet.Unicode)] static extern int CLSIDFromProgID(string p,out Guid g);
 [DllImport("oleaut32.dll",PreserveSig=false)] static extern void GetActiveObject(ref Guid g,IntPtr z,[MarshalAs(UnmanagedType.IUnknown)]out object o);
 public static object Get(){Guid g; CLSIDFromProgID("Visio.Application",out g);object o;GetActiveObject(ref g,IntPtr.Zero,out o);return o;}
}
'@
$v=[ActiveVisio]::Get()
$d=$null
foreach($candidate in $v.Documents){if($candidate.Name -eq 'FedHELM-architecture-reference.vsdx'){$d=$candidate;break}}
if(-not $d){throw 'Expected generated document is not open'}
$p=$d.Pages.Item(1)
$p.PageSheet.CellsU('DrawingResizeType').FormulaU='0'
$p.PageSheet.CellsU('PageWidth').FormulaU='16.98 in'
$p.PageSheet.CellsU('PageHeight').FormulaU='10.72 in'
foreach($shape in $p.Shapes){
 if($shape.Master -and $shape.Master.NameU -eq 'Rounded Rectangle'){
  $radius=if($shape.NameU -in @('ends','edge')){'0.12 in'}else{'0.065 in'}
  foreach($corner in @('TopLeft','TopRight','BotLeft','BotRight')){$shape.CellsU('User.'+$corner+'Offset').FormulaU=$radius}
 }
}
foreach($s in $p.Shapes){
 foreach($cell in @('LeftMargin','RightMargin','TopMargin','BottomMargin')) {try{$s.CellsU($cell).FormulaU='0.025 in'}catch{}}
 if($s.Master -and $s.Master.NameU -eq 'Rounded Rectangle'){
  $s.CellsU('Rounding').FormulaU=if($s.NameU -in @('ends','edge')){'0.12 in'}else{'0.06 in'}
 }
 if($s.NameU -eq 'functions'){$s.CellsU('LinePattern').FormulaU='2'}
 if($s.NameU -eq 'alg1'){$s.CellsU('Char.Size').FormulaU='14.5 pt'}
}
$v.ActiveWindow.DeselectAll()
try{$v.ActiveWindow.ShowGrid=$false}catch{}
$d.Save()
$d.Save()
$v.ActiveWindow.ViewFit=1
Write-Output ('Saved: '+$d.FullName)
Write-Output ('Editable shapes: '+$p.Shapes.Count)
